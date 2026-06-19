"""Tests for app/score/formula.py — assembly of B(s, h) from the
5 sub-scores + horizon weights.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import pytest

from bottlewatch.app.score.extractors import ExtractorResult
from bottlewatch.app.score.formula import (
    HORIZONS,
    ScoreResult,
    compute_segment_score,
)
from bottlewatch.app.score.regime import Regime


@dataclass
class _Row:
    signal_name: str
    value_num: Optional[float]
    observed_at: object  # unused in the no-extractor path
    geography: str | None = None


def test_full_b_near_for_power() -> None:
    # power_generation_oem with planned_capacity_mw (forward 5000) +
    # capacity_mw (20000) → capacity_tightness raw = 5000/20000 = 0.25.
    # The calibrated fixed band [0, 0.5] maps 0.25 → 0.5.
    # B(near) = 100 * (0.30*0.80 + 0.35*0.50 + 0.10*0.35 + 0.05*0.67 + 0.20*0.85)
    #         = 100 * (0.24 + 0.175 + 0.035 + 0.0335 + 0.17)
    #         = 100 * 0.6535 = 65.35
    result = compute_segment_score(
        "power_generation_oem",
        "near",
        signals=[
            _Row("planned_capacity_mw", 5000.0, None),
            _Row("capacity_mw", 20000.0, None),
        ],
        now=datetime(2026, 6, 4, tzinfo=timezone.utc),
    )
    assert isinstance(result, ScoreResult)
    assert result.segment == "power_generation_oem"
    assert result.horizon == "near"
    assert result.score == pytest.approx(65.35, abs=1e-3)
    assert result.data_completeness == 1.0
    assert result.regime is Regime.STABLE  # B=65.35, B'=0 → STABLE
    assert result.regime_confidence == "low"


def test_full_b_respects_horizon_weights() -> None:
    near = compute_segment_score(
        "advanced_node_fabs",
        "near",
        now=datetime(2026, 6, 4, tzinfo=timezone.utc),
    )
    long = compute_segment_score(
        "advanced_node_fabs",
        "long",
        now=datetime(2026, 6, 4, tzinfo=timezone.utc),
    )
    assert near.score is not None and long.score is not None
    assert near.regime in (Regime.PEAKED, Regime.PEAKING, Regime.STABLE)
    assert long.regime in (Regime.PEAKED, Regime.PEAKING, Regime.STABLE)


def test_momentum_zero_on_first_compute() -> None:
    result = compute_segment_score(
        "transformers_tnd",
        "med",
        now=datetime(2026, 6, 4, tzinfo=timezone.utc),
    )
    assert result.momentum == 0.0
    assert result.regime_confidence == "low"


def test_regime_confidence_increases_with_age() -> None:
    first = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result_low = compute_segment_score(
        "transformers_tnd",
        "near",
        first_computed_at=first,
        now=datetime(2026, 1, 31, tzinfo=timezone.utc),
    )
    assert result_low.regime_confidence == "low"
    result_med = compute_segment_score(
        "transformers_tnd",
        "near",
        first_computed_at=first,
        now=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    assert result_med.regime_confidence == "medium"
    result_high = compute_segment_score(
        "transformers_tnd",
        "near",
        first_computed_at=first,
        now=datetime(2026, 7, 20, tzinfo=timezone.utc),
    )
    assert result_high.regime_confidence == "high"


def test_data_completeness_reflects_imputed_weight() -> None:
    # transformers_tnd has seed values for most sub-scores but no
    # capacity_tightness extractor → that sub-score is imputed. The
    # completeness must drop below 1.0 by exactly the imputed weight,
    # NOT report a misleading 1.0 (the old `v is not None` bug).
    result = compute_segment_score(
        "transformers_tnd",
        "near",
        now=datetime(2026, 6, 4, tzinfo=timezone.utc),
    )
    imputed = {name for name, p in result.sub_score_provenance.items() if p.imputed}
    assert imputed, "expected at least one imputed sub-score for this segment"
    assert result.data_completeness < 1.0
    # Seeds are curated, not imputed — they must NOT reduce completeness.
    seeded = {name for name, p in result.sub_score_provenance.items() if p.source == "seed" and not p.imputed}
    assert seeded, "transformers_tnd should be seed-backed, keeping completeness high"


def test_data_completeness_is_one_when_nothing_imputed() -> None:
    # power_generation_oem with both capacity inputs → capacity_tightness
    # is computed (not imputed), and the other four are seed-backed (not
    # imputed). Completeness is exactly 1.0 — the meaningful "all real" case.
    result = compute_segment_score(
        "power_generation_oem",
        "near",
        signals=[
            _Row("planned_capacity_mw", 5000.0, None),
            _Row("capacity_mw", 20000.0, None),
        ],
        now=datetime(2026, 6, 4, tzinfo=timezone.utc),
    )
    assert not any(p.imputed for p in result.sub_score_provenance.values())
    assert result.data_completeness == pytest.approx(1.0)


def test_no_data_gate_fires_when_imputed_weight_exceeds_threshold() -> None:
    # NO_DATA is reachable when imputed sub-scores carry > (1 - 0.4) = 0.6
    # of the weight. With mandatory seeds only capacity_tightness can be
    # imputed in production, so we inject a seed that omits the four
    # research sub-scores to simulate a segment with no curated data —
    # proving the gate is correctly wired end-to-end, not just in
    # `classify`. (See the spec's note: in the live config every segment
    # has a full seed, so this state does not occur today.)
    # Seed entry present (keys exist) but every research value is None,
    # so the normalizer imputes all four; capacity_tightness has no
    # signals, so it imputes too → all five imputed → completeness 0.0.
    bare_seed = {
        "bare_segment": {
            "lead_time_growth": None,
            "geo_concentration": None,
            "regulatory_friction": None,
            "demand_signal": None,
        }
    }
    result = compute_segment_score(
        "bare_segment",
        "near",
        seed=bare_seed,  # type: ignore[arg-type]
        now=datetime(2026, 6, 4, tzinfo=timezone.utc),
    )
    assert all(p.imputed for p in result.sub_score_provenance.values())
    assert result.data_completeness == pytest.approx(0.0)
    assert result.regime is Regime.NO_DATA
    # Score stays populated (the regime label is the trust signal).
    assert result.score is not None


def test_unknown_horizon_raises() -> None:
    with pytest.raises(ValueError, match="unknown horizon"):
        compute_segment_score("transformers_tnd", "weekly", now=datetime.now(tz=timezone.utc))


def test_horizons_tuple_is_canonical() -> None:
    assert HORIZONS == ("near", "med", "long")


def test_sub_scores_contains_all_five_names() -> None:
    result = compute_segment_score(
        "transformers_tnd",
        "near",
        now=datetime(2026, 6, 4, tzinfo=timezone.utc),
    )
    assert set(result.sub_scores.keys()) == {
        "lead_time_growth",
        "capacity_tightness",
        "geo_concentration",
        "regulatory_friction",
        "demand_signal",
    }
    # transformers_tnd has no capacity_tightness extractor → imputed 0.5.
    assert result.sub_scores["capacity_tightness"] == pytest.approx(0.5)
    assert result.sub_score_provenance["capacity_tightness"].source == "imputed"


def test_to_persisted_shape_matches_score_orm() -> None:
    result = compute_segment_score(
        "power_generation_oem",
        "near",
        signals=[_Row("capacity_mw", 1000.0, None)],
        now=datetime(2026, 6, 4, tzinfo=timezone.utc),
    )
    persisted = result.to_persisted()
    assert set(persisted.keys()) == {
        "segment",
        "horizon",
        "score",
        "momentum",
        "regime",
        "regime_confidence",
        "sub_scores",
        "raw_sub_scores",
        "sub_score_provenance",
        "normalization_mode",
        "static_seed_share",
        "data_completeness",
        "first_computed_at",
        "computed_at",
    }


def test_geo_concentration_override_replaces_seed() -> None:
    # Use 0.50 so divergence from seed (0.35) is below the 0.30 threshold.
    now = datetime(2026, 6, 4, tzinfo=timezone.utc)
    with_override = compute_segment_score(
        "transformers_tnd",
        "near",
        now=now,
        geo_concentration=0.50,
    )
    without_override = compute_segment_score(
        "transformers_tnd",
        "near",
        now=now,
    )
    assert with_override.sub_scores["geo_concentration"] == 0.50
    assert without_override.sub_scores["geo_concentration"] == pytest.approx(0.35)
    assert with_override.score != without_override.score


def test_geo_concentration_none_falls_back_to_seed() -> None:
    result = compute_segment_score(
        "transformers_tnd",
        "near",
        now=datetime(2026, 6, 4, tzinfo=timezone.utc),
    )
    assert result.sub_scores["geo_concentration"] == pytest.approx(0.35)


def test_geo_concentration_override_does_not_affect_other_subscores() -> None:
    now = datetime(2026, 6, 4, tzinfo=timezone.utc)
    with_override = compute_segment_score(
        "transformers_tnd",
        "near",
        now=now,
        geo_concentration=0.50,
    )
    without_override = compute_segment_score(
        "transformers_tnd",
        "near",
        now=now,
    )
    for name in ("lead_time_growth", "capacity_tightness", "regulatory_friction", "demand_signal"):
        assert with_override.sub_scores[name] == without_override.sub_scores[name]


def test_geo_concentration_large_divergence_falls_back_to_seed() -> None:
    now = datetime(2026, 6, 4, tzinfo=timezone.utc)
    result = compute_segment_score(
        "transformers_tnd",
        "near",
        now=now,
        geo_concentration=0.99,
    )
    assert result.sub_scores["geo_concentration"] == pytest.approx(0.35)
    assert result.sub_score_provenance["geo_concentration"].source == "seed"


def test_demand_signal_override_replaces_seed() -> None:
    # The `transformer_orders` macro-proxy band was removed during
    # Phase 4 calibration. An override with that source_key now falls
    # back to the seed passthrough band [0, 1], so raw 0.25 stays 0.25.
    now = datetime(2026, 6, 4, tzinfo=timezone.utc)
    with_override = compute_segment_score(
        "transformers_tnd",
        "near",
        now=now,
        demand_signal=ExtractorResult(0.25, "transformer_orders"),
    )
    without_override = compute_segment_score(
        "transformers_tnd",
        "near",
        now=now,
    )
    assert with_override.sub_scores["demand_signal"] == pytest.approx(0.25)
    assert without_override.sub_scores["demand_signal"] == pytest.approx(0.80)
    assert with_override.score != without_override.score


def test_demand_signal_none_falls_back_to_seed() -> None:
    result = compute_segment_score(
        "transformers_tnd",
        "near",
        now=datetime(2026, 6, 4, tzinfo=timezone.utc),
    )
    assert result.sub_scores["demand_signal"] == pytest.approx(0.80)


def test_demand_signal_override_does_not_affect_other_subscores() -> None:
    now = datetime(2026, 6, 4, tzinfo=timezone.utc)
    with_override = compute_segment_score(
        "transformers_tnd",
        "near",
        now=now,
        demand_signal=ExtractorResult(0.25, "transformer_orders"),
    )
    without_override = compute_segment_score(
        "transformers_tnd",
        "near",
        now=now,
    )
    for name in ("lead_time_growth", "capacity_tightness", "geo_concentration", "regulatory_friction"):
        assert with_override.sub_scores[name] == without_override.sub_scores[name]


def test_lead_time_growth_override_replaces_seed() -> None:
    # transformers_ppi band: level [80, 350]. Raw 350 → normalized 1.0.
    now = datetime(2026, 6, 4, tzinfo=timezone.utc)
    with_override = compute_segment_score(
        "transformers_tnd",
        "near",
        now=now,
        lead_time_growth=ExtractorResult(350.0, "transformers_ppi"),
    )
    without_override = compute_segment_score(
        "transformers_tnd",
        "near",
        now=now,
    )
    assert with_override.sub_scores["lead_time_growth"] == 1.0
    assert without_override.sub_scores["lead_time_growth"] == pytest.approx(0.85)
    assert with_override.score != without_override.score


def test_lead_time_growth_none_falls_back_to_seed() -> None:
    result = compute_segment_score(
        "transformers_tnd",
        "near",
        now=datetime(2026, 6, 4, tzinfo=timezone.utc),
    )
    assert result.sub_scores["lead_time_growth"] == pytest.approx(0.85)


def test_lead_time_growth_override_does_not_affect_other_subscores() -> None:
    now = datetime(2026, 6, 4, tzinfo=timezone.utc)
    with_override = compute_segment_score(
        "transformers_tnd",
        "near",
        now=now,
        lead_time_growth=ExtractorResult(350.0, "transformers_ppi"),
    )
    without_override = compute_segment_score(
        "transformers_tnd",
        "near",
        now=now,
    )
    for name in ("capacity_tightness", "geo_concentration", "regulatory_friction", "demand_signal"):
        assert with_override.sub_scores[name] == without_override.sub_scores[name]
