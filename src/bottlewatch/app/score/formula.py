"""Score formula assembly (methodology §1 + §3).

Pulls the 4 research sub-scores from `research_values`, the computed
sub-scores from `extractors`, normalizes every raw value through
`SubScoreNormalizer`, then computes:

    B(s, h) = 100 * Σ_i w_i(h) * normalize(s_i)

with the horizon weights from methodology §3:

    | Sub-score               | Near  | Med   | Long  |
    |-------------------------|------:|------:|------:|
    | lead_time_growth        | 0.30  | 0.20  | 0.10  |
    | capacity_tightness      | 0.35  | 0.20  | 0.10  |
    | geo_concentration       | 0.10  | 0.20  | 0.30  |
    | regulatory_friction     | 0.05  | 0.15  | 0.30  |
    | demand_signal           | 0.20  | 0.25  | 0.20  |
    | Total                   | 1.00  | 1.00  | 1.00  |

Momentum `B'(s, h)` is the 6-month change in B. The recompute job
passes the trailing 6mo of computed B values via the `b_history`
argument; on the first compute `b_history` is empty and B' = 0.

This module is pure. No I/O, no datetime.now() (caller passes
`now` for regime confidence).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from bottlewatch.app.score import extractors
from bottlewatch.app.score.normalize import normalize_subscore
from bottlewatch.app.score.regime import (
    FAST_RESOLVE_THRESHOLD,
    NO_DATA_THRESHOLD,
    Regime,
    RegimeResult,
    classify,
)
from bottlewatch.app.score.research_values import Seed, SeedEntry, for_segment

HORIZONS: tuple[str, ...] = ("near", "med", "long")

# methodology §3. Per-horizon weights for the 5 sub-scores.
# Indexed [horizon][sub_score_name] -> weight.
_WEIGHTS: dict[str, dict[str, float]] = {
    "near": {
        "lead_time_growth": 0.30,
        "capacity_tightness": 0.35,
        "geo_concentration": 0.10,
        "regulatory_friction": 0.05,
        "demand_signal": 0.20,
    },
    "med": {
        "lead_time_growth": 0.20,
        "capacity_tightness": 0.20,
        "geo_concentration": 0.20,
        "regulatory_friction": 0.15,
        "demand_signal": 0.25,
    },
    "long": {
        "lead_time_growth": 0.10,
        "capacity_tightness": 0.10,
        "geo_concentration": 0.30,
        "regulatory_friction": 0.30,
        "demand_signal": 0.20,
    },
}

_SUB_SCORE_NAMES: tuple[str, ...] = (
    "lead_time_growth",
    "capacity_tightness",
    "geo_concentration",
    "regulatory_friction",
    "demand_signal",
)

# Confidence gating. methodology §1: <2y history → median. For regime
# confidence, we use the recompute-history (B values) not the signal
# history. <90 days = low, <180 = medium, >=180 = high.
_CONFIDENCE_LOW_DAYS = 90
_CONFIDENCE_MEDIUM_DAYS = 180

# If the live universe HHI diverges from the research seed by more than
# this (absolute), keep the seed value while the override file is being
# curated.
_HHI_SEED_DIVERGENCE_THRESHOLD = 0.30


@dataclass(frozen=True)
class SubScoreProvenance:
    """Provenance for one sub-score value."""

    source: str  # "extractor" | "seed" | "imputed"
    confidence: str  # "high" | "medium" | "low"
    imputed: bool


@dataclass(frozen=True)
class SubScore:
    """One of the 5 sub-scores and whether it was computed or
    hand-curated. `value` is None when no extractor exists for the
    segment; in that case the segment's completeness drops.
    """

    name: str
    value: float | None
    source: str  # "extractor" | "seed" | "imputed"
    confidence: str  # "high" | "medium" | "low"
    imputed: bool = False


@dataclass(frozen=True)
class ScoreResult:
    """The output of `compute_segment_score` for one (segment, horizon).

    `sub_scores` is a 5-tuple dict keyed by sub-score name; values are
    always floats because the normalizer substitutes 0.5 for missing
    values and flags them as imputed. `score` and `momentum` are None
    for NO_DATA rows.
    """

    segment: str
    horizon: str
    score: float | None
    momentum: float | None
    regime: Regime
    regime_confidence: str
    sub_scores: dict[str, float]
    raw_sub_scores: dict[str, float | None]
    sub_score_provenance: dict[str, SubScoreProvenance]
    normalization_mode: str
    static_seed_share: float
    data_completeness: float
    fast_resolve: bool
    first_computed_at: datetime
    computed_at: datetime

    def to_persisted(self) -> dict[str, object]:
        """Column-shape dict for bulk insert into the `scores` table."""
        return {
            "segment": self.segment,
            "horizon": self.horizon,
            "score": self.score,
            "momentum": self.momentum,
            "regime": self.regime.value,
            "regime_confidence": self.regime_confidence,
            "sub_scores": self.sub_scores,
            "raw_sub_scores": self.raw_sub_scores,
            "sub_score_provenance": {
                name: {"source": p.source, "confidence": p.confidence, "imputed": p.imputed}
                for name, p in self.sub_score_provenance.items()
            },
            "normalization_mode": self.normalization_mode,
            "static_seed_share": self.static_seed_share,
            "data_completeness": self.data_completeness,
            "first_computed_at": self.first_computed_at,
            "computed_at": self.computed_at,
        }


def compute_segment_score(
    segment: str,
    horizon: str,
    *,
    signals: Iterable[extractors.SignalLike] = (),
    seed: Seed | None = None,
    b_history: list[tuple[datetime, float]] | None = None,
    first_computed_at: datetime | None = None,
    now: datetime,
    geo_concentration: float | None = None,
    demand_signal: extractors.ExtractorResult | None = None,
    lead_time_growth: extractors.ExtractorResult | None = None,
    capacity_tightness: extractors.ExtractorResult | None = None,
    normalization_mode: str = "fixed",
    sub_score_history: dict[tuple[str, str], list[tuple[float, float]]] | None = None,
) -> ScoreResult:
    """Compute B(s, h) and the regime per the methodology.

    Args:
        segment: the segment slug (e.g. "power_generation_oem").
        horizon: one of "near" | "med" | "long".
        signals: rows for this segment, passed to the capacity extractor.
            The recompute job filters by segment before calling.
        seed: the parsed scoring_seed.json; defaults to on-disk load.
        b_history: trailing 6mo of (computed_at, B) pairs for momentum.
            Empty list = first compute → B' = 0.
        first_computed_at: when this segment's score was first written.
            The recompute job reads the existing row to set this.
        now: the recompute timestamp (caller passes utcnow()).
        geo_concentration: live HHI value in [0, 1] (already normalized).
            When None, falls back to the research seed.
        demand_signal: raw extractor result for demand_signal, or None
            to fall back to the research seed.
        lead_time_growth: raw extractor result for lead_time_growth, or
            None to fall back to the research seed.
        capacity_tightness: raw extractor result for capacity_tightness,
            or None to let the extractor run on `signals`.
        normalization_mode: "fixed" or "rolling". Passed to the normalizer.
        sub_score_history: trailing history per (segment, sub_score_name)
            used by rolling normalization. Keys are tuples.
    """
    if horizon not in _WEIGHTS:
        raise ValueError(f"unknown horizon: {horizon!r}; expected one of {HORIZONS}")

    history_lookup = sub_score_history or {}
    research: SeedEntry = for_segment(segment, seed)

    # Run the capacity_tightness extractor if no override was passed.
    computed_capacity = capacity_tightness
    if computed_capacity is None:
        computed_capacity = extractors.capacity_tightness(segment, list(signals))

    # Build raw sub-score inputs. geo_concentration is already a [0,1]
    # HHI; the other sub-scores are raw values that need normalization.
    # If no live override exists, use the research seed.
    raw_inputs: dict[str, extractors.ExtractorResult] = {
        "lead_time_growth": (
            lead_time_growth
            if lead_time_growth is not None
            else extractors.ExtractorResult(research["lead_time_growth"], "seed")
        ),
        "capacity_tightness": (
            computed_capacity if computed_capacity is not None else extractors.ExtractorResult(None, "imputed")
        ),
        "geo_concentration": _geo_input(segment, research, geo_concentration),
        "regulatory_friction": extractors.ExtractorResult(research["regulatory_friction"], "seed"),
        "demand_signal": (
            demand_signal
            if demand_signal is not None
            else extractors.ExtractorResult(research["demand_signal"], "seed")
        ),
    }

    # Normalize every raw value. The normalizer handles None → 0.5 with
    # explicit imputed provenance, seed passthrough, and fixed/rolling bands.
    sub_scores: dict[str, float] = {}
    raw_sub_scores: dict[str, float | None] = {}
    provenance: dict[str, SubScoreProvenance] = {}
    for name in _SUB_SCORE_NAMES:
        inp = raw_inputs[name]
        normalized = normalize_subscore(
            name,
            inp.raw_value,
            inp.source_key,
            normalization_mode,  # type: ignore[arg-type]
            history=history_lookup.get((segment, name)),
            log_prefix=f"{segment}/{horizon}: ",
        )
        sub_scores[name] = normalized.value
        raw_sub_scores[name] = normalized.raw_value
        provenance[name] = SubScoreProvenance(
            source=normalized.source,
            confidence=normalized.confidence,
            imputed=normalized.imputed,
        )

    completeness = sum(1 for v in sub_scores.values() if v is not None) / len(sub_scores)

    # Score: 100 * Σ w_i * s_i. The normalizer has already substituted
    # missing values with 0.5 and flagged them as imputed, so every
    # sub_score here is a usable float.
    b = 100.0 * sum(_WEIGHTS[horizon][name] * sub_scores[name] for name in _SUB_SCORE_NAMES)

    # Share of the weighted score driven by static seeds.
    seed_weight = sum(
        _WEIGHTS[horizon][name]
        for name in _SUB_SCORE_NAMES
        if provenance[name].source == "seed" and not provenance[name].imputed
    )
    static_seed_share = seed_weight

    momentum = _momentum(b, b_history or [], now)
    classified: RegimeResult = classify(b, momentum, completeness)
    confidence = _regime_confidence(first_computed_at, now)

    return ScoreResult(
        segment=segment,
        horizon=horizon,
        score=b,
        momentum=momentum,
        regime=classified.regime,
        regime_confidence=confidence,
        sub_scores=sub_scores,
        raw_sub_scores=raw_sub_scores,
        sub_score_provenance=provenance,
        normalization_mode=normalization_mode,
        static_seed_share=static_seed_share,
        data_completeness=completeness,
        fast_resolve=classified.fast_resolve,
        first_computed_at=first_computed_at or now,
        computed_at=now,
    )


def _geo_input(
    segment: str,
    research: SeedEntry,
    geo_concentration: float | None,
) -> extractors.ExtractorResult:
    """Build the geo_concentration input, falling back to seed on large divergence."""
    seed_hhi = research["geo_concentration"]
    if geo_concentration is None:
        return extractors.ExtractorResult(seed_hhi, "seed")
    if abs(geo_concentration - seed_hhi) > _HHI_SEED_DIVERGENCE_THRESHOLD:
        return extractors.ExtractorResult(seed_hhi, "seed")
    return extractors.ExtractorResult(geo_concentration, "hhi")


def _momentum(
    b_now: float | None,
    history: list[tuple[datetime, float]],
    now: datetime,
) -> float | None:
    """B'(s, h) = 100 * (B_now − B_6mo) / B_6mo, capped to [-100, +100].

    Per methodology §7.5, we use the 6-month *median* of B (not the
    end-point) to suppress noise. A segment with B_6mo ≈ 0 returns
    +100 by convention.
    """
    if b_now is None:
        return None
    if not history:
        return 0.0
    # Collect all B values within a 30-day window around t-6mo.
    target = now - timedelta(days=180)
    window = [v for ts, v in history if abs((ts - target).total_seconds()) <= 15 * 86_400]
    if not window:
        return 0.0  # no history near t-6mo → treat as first compute
    # Median of the 6-month window.
    sorted_w = sorted(window)
    n = len(sorted_w)
    b_then = sorted_w[n // 2] if n % 2 == 1 else (sorted_w[n // 2 - 1] + sorted_w[n // 2]) / 2.0
    # Methodology edge case: B_6mo < 5 ≈ effectively zero → +100 by convention.
    if b_then < 5.0:
        return 100.0
    raw = 100.0 * (b_now - b_then) / b_then
    return max(-100.0, min(100.0, raw))


def _regime_confidence(first_computed_at: datetime | None, now: datetime) -> str:
    """Low / medium / high based on days since first compute.

    `first_computed_at` is None only for segments that have never
    been computed before (the first job run). In that case we treat
    the segment as fresh → low confidence.
    """
    if first_computed_at is None:
        return "low"
    age_days = (now - first_computed_at).total_seconds() / 86_400
    if age_days < _CONFIDENCE_LOW_DAYS:
        return "low"
    if age_days < _CONFIDENCE_MEDIUM_DAYS:
        return "medium"
    return "high"


# Re-export for tests and callers.
__all__ = [
    "HORIZONS",
    "NO_DATA_THRESHOLD",
    "FAST_RESOLVE_THRESHOLD",
    "ScoreResult",
    "SubScore",
    "SubScoreProvenance",
    "compute_segment_score",
]
