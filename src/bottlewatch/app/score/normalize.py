"""5-year rolling-band and fixed-band normalization (methodology §1).

The SubScoreNormalizer is the single source of truth for turning a raw
sub-score value into a [0, 1] score. It supports:

- `fixed` mode: externalized bands from `research/config/score_bands.json`.
- `rolling` mode: 5-year min/max (winsorized at 5th/95th) with a 2-year
  maturity gate; falls back to fixed when history is too short or flat.
- `None` input: returns 0.5 (universe median placeholder) with explicit
  `imputed=True` provenance, replacing the silent substitution in
  `formula.py`.
- Seed values: pass through unchanged (band min=0, max=1).

Every result carries the band bounds and normalization mode so the
sub_score_history table can audit them.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

_LOGGER = logging.getLogger(__name__)

_HISTORY_MIN_DAYS = 730  # 2y
_UNINFORMED_VALUE = 0.5
_ROLLING_WINSOR_LOW = 0.05
_ROLLING_WINSOR_HIGH = 0.95

# Project root: src/bottlewatch/app/score/normalize.py -> ../../../..
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_BANDS_PATH = _PROJECT_ROOT / "research" / "config" / "score_bands.json"


def _load_bands(path: Path) -> dict:
    """Load the score-bands JSON; raise on missing/malformed.

    Like `regime.py`, we load at import time and fail hard on a bad
    config so the operator notices drift immediately.
    """
    if not path.exists():
        raise FileNotFoundError(f"score bands file not found at {path}")
    return json.loads(path.read_text(encoding="utf-8"))


_BANDS = _load_bands(_DEFAULT_BANDS_PATH)
BANDS_VERSION: str = _BANDS.get("version", "unknown")
BANDS_FROZEN_SINCE: str | None = _BANDS.get("frozen_since")
BANDS_CHANGELOG: list[dict] = _BANDS.get("changelog", [])


def reload_bands(path: Path | None = None) -> None:
    """Reload band configuration (mostly for tests)."""
    global _BANDS, BANDS_VERSION, BANDS_FROZEN_SINCE, BANDS_CHANGELOG
    _BANDS = _load_bands(path or _DEFAULT_BANDS_PATH)
    BANDS_VERSION = _BANDS.get("version", "unknown")
    BANDS_FROZEN_SINCE = _BANDS.get("frozen_since")
    BANDS_CHANGELOG = _BANDS.get("changelog", [])


@dataclass(frozen=True)
class NormalizedSubScore:
    """Result of normalizing one raw sub-score."""

    value: float
    raw_value: float | None
    source: str  # "extractor" | "seed" | "imputed"
    confidence: str  # "high" | "medium" | "low"
    imputed: bool
    normalization_mode: str  # "fixed" | "rolling" | "fallback_to_fixed"
    band_min: float | None
    band_max: float | None


@dataclass(frozen=True)
class _Band:
    min: float
    max: float


def _get_band(name: str, source_key: str) -> _Band:
    """Return the fixed band for a (sub-score, source-key) pair.

    Falls back to the seed band (0, 1) when no specific band is found.
    """
    sub_bands = _BANDS.get("bands", {})
    bands_for_name = sub_bands.get(name, {})
    band = bands_for_name.get(source_key)
    if band is None:
        band = bands_for_name.get("seed", {"min": 0.0, "max": 1.0})
    return _Band(min=float(band["min"]), max=float(band["max"]))


def _map_linear(raw: float, band: _Band) -> float:
    """Map raw value linearly from [band.min, band.max] to [0, 1]."""
    if band.max == band.min:
        return _UNINFORMED_VALUE
    if raw <= band.min:
        return 0.0
    if raw >= band.max:
        return 1.0
    return (raw - band.min) / (band.max - band.min)


def _rolling_band(history: list[float]) -> _Band | None:
    """Build a 5th/95th winsorized band from historical values.

    Returns None if history is empty or has zero variance.
    """
    if not history:
        return None
    values = sorted(history)
    n = len(values)
    if n < 2 or values[0] == values[-1]:
        return None
    lo_idx = int(n * _ROLLING_WINSOR_LOW)
    hi_idx = int(n * _ROLLING_WINSOR_HIGH)
    lo_idx = max(0, min(lo_idx, n - 1))
    hi_idx = max(0, min(hi_idx, n - 1))
    band_min = values[lo_idx]
    band_max = values[hi_idx]
    if band_min == band_max:
        return None
    return _Band(min=band_min, max=band_max)


def _history_span_days(history: list[tuple[float, float]]) -> int:
    """Return span in days from timestamped (ts, value) history."""
    if len(history) < 2:
        return 0
    timestamps = [t for t, _ in history]
    return int((max(timestamps) - min(timestamps)) / 86_400)


def history_is_mature(history: list[tuple[float, float]]) -> bool:
    """True if the timestamped history spans at least 2 years."""
    return _history_span_days(history) >= _HISTORY_MIN_DAYS


def normalize_5y(value: float, history: list[float]) -> float:
    """Map a raw value to [0, 1] using a 5-year min/max band.

    Convenience wrapper kept for tests and callers that do not need
    the full SubScoreNormalizer machinery. Uses 5th/95th winsorization.
    """
    band = _rolling_band(history)
    if band is None:
        return _UNINFORMED_VALUE
    return _map_linear(value, band)


def _confidence(
    source: str,
    normalization_mode: str,
    history_span_days: int,
) -> str:
    """Confidence based on source and rolling-history maturity."""
    if source == "imputed":
        return "low"
    if source == "seed":
        return "low"
    # source == "extractor"
    if normalization_mode == "rolling":
        if history_span_days >= _HISTORY_MIN_DAYS:
            return "high"
        return "medium"
    return "high"  # fixed mode with live extractor


def normalize_subscore(
    name: str,
    raw: float | None,
    source_key: str,
    mode: Literal["fixed", "rolling"],
    history: list[tuple[float, float]] | None = None,
    log_prefix: str = "",
) -> NormalizedSubScore:
    """Normalize a raw sub-score value to [0, 1].

    Args:
        name: sub-score name (e.g. "lead_time_growth").
        raw: the raw metric value, or None when the extractor had no data.
        source_key: band lookup key returned by the extractor (e.g.
            "transformers_ppi", "seed", "hhi").
        mode: "fixed" uses the JSON band; "rolling" uses the 5-year
            trailing history when mature enough.
        history: optional list of (unix_timestamp, raw_value) pairs for
            rolling mode. Oldest first is not required; the function sorts.
        log_prefix: optional prefix for calibration warnings.

    Returns:
        NormalizedSubScore with the normalized value, raw value,
        provenance, and band bounds.
    """
    history = history or []
    fixed_band = _get_band(name, source_key)

    # Seed values are already normalized; no-op.
    if source_key == "seed" and raw is not None:
        return NormalizedSubScore(
            value=float(raw),
            raw_value=raw,
            source="seed",
            confidence="low",
            imputed=False,
            normalization_mode="fixed",
            band_min=0.0,
            band_max=1.0,
        )

    # Imputed value when extractor had no data.
    if raw is None:
        return NormalizedSubScore(
            value=_UNINFORMED_VALUE,
            raw_value=None,
            source="imputed",
            confidence="low",
            imputed=True,
            normalization_mode="fixed",
            band_min=fixed_band.min,
            band_max=fixed_band.max,
        )

    span_days = _history_span_days(history)
    # Rolling band gates: 1 year minimum (medium confidence), 2 years
    # for high confidence. This lets backfilled histories participate
    # in rolling normalization earlier than the strict 2-year
    # methodology default, with lower confidence.
    use_rolling = mode == "rolling" and span_days >= 365 and len(history) >= 2

    if use_rolling:
        raw_history = [v for _, v in history]
        band = _rolling_band(raw_history)
        if band is not None:
            # Warn if rolling band is far wider than the fixed band.
            if band.min < fixed_band.min / 2 or band.max > fixed_band.max * 2:
                _LOGGER.warning(
                    "%s%s rolling band [%.3f, %.3f] diverges from fixed band [%.3f, %.3f]",
                    log_prefix,
                    name,
                    band.min,
                    band.max,
                    fixed_band.min,
                    fixed_band.max,
                )
            normalization_mode = "rolling"
        else:
            band = fixed_band
            normalization_mode = "fallback_to_fixed"
    else:
        band = fixed_band
        normalization_mode = "fixed" if mode == "fixed" else "fallback_to_fixed"

    value = _map_linear(float(raw), band)
    conf = _confidence("extractor", normalization_mode, span_days)

    return NormalizedSubScore(
        value=value,
        raw_value=raw,
        source="extractor",
        confidence=conf,
        imputed=False,
        normalization_mode=normalization_mode,
        band_min=band.min,
        band_max=band.max,
    )
