"""Regime classification from (B, B') per methodology §7.6.

The 7-cell table + the `NO_DATA` gate are read at import time from
`research/06_regime_thresholds.json` so the calibration is a
single-file edit. The v1 plan documented (60, ±5) as a placeholder;
the M2 calibration is (70, +20/0/+30/-15). See the JSON's
`_comment` field and the methodology §7.6 for the rationale.

Seven cells from the level-and-momentum plane:

    B >= 70 AND B' >= +20  → PEAKING
    B >= 70 AND 0 <= B' < 20 → PEAKED
    B >= 70 AND B' <  0    → RESOLVING  (fast_resolve if B' < -50)
    B <  70 AND B' >= +30  → EMERGING
    30 <= B < 70 AND B' <= -15 → RESOLVING (moderate; M2-v2 — fills the lower-right gap)
    30 <= B < 70 AND -15 < B' < +30 → STABLE
    B <  30 AND B' <= -15  → RESOLVING-from-low

An 8th synthetic label, NO_DATA, is added for segments where the
formula did not have enough information to compute a meaningful B
(`data_completeness < no_data_threshold`). We still write a
`scores` row so the scoreboard can render an honest "no data"
badge.

The 7-cell table is exhaustive; there is no fallthrough. The
classifier is pure: `(B, B', data_completeness) -> Regime`.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

_LOGGER = logging.getLogger(__name__)


class Regime(StrEnum):
    PEAKING = "PEAKING"
    PEAKED = "PEAKED"
    RESOLVING = "RESOLVING"
    EMERGING = "EMERGING"
    STABLE = "STABLE"
    RESOLVING_FROM_LOW = "RESOLVING_FROM_LOW"
    NO_DATA = "NO_DATA"


REGIMES: tuple[Regime, ...] = (
    Regime.PEAKING,
    Regime.PEAKED,
    Regime.RESOLVING,
    Regime.EMERGING,
    Regime.STABLE,
    Regime.RESOLVING_FROM_LOW,
    Regime.NO_DATA,
)


# ---------------------------------------------------------------------------
# Load calibration from research/06_regime_thresholds.json
# ---------------------------------------------------------------------------

# Project root: src/bottlewatch/app/score/regime.py -> ../../../../..  (5 levels)
_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_THRESHOLDS = _PROJECT_ROOT / "research" / "06_regime_thresholds.json"


def _load_thresholds(path: Path) -> dict:
    """Read the thresholds JSON; raise on missing/malformed.

    Calibration is loaded once at import time. A bad file is a
    hard error — better to fail at startup than to silently fall
    back to a default that may not match the published spec.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"regime thresholds file not found at {path}; expected research/06_regime_thresholds.json"
        )
    return json.loads(path.read_text())


_THRESHOLDS = _load_thresholds(_DEFAULT_THRESHOLDS)

NO_DATA_THRESHOLD: float = _THRESHOLDS["no_data_threshold"]
B_THRESHOLD: float = _THRESHOLDS["b_threshold"]
FAST_RESOLVE_THRESHOLD: float = _THRESHOLDS["fast_resolve_momentum_max"]
_THRESHOLDS_VERSION: str = _THRESHOLDS.get("version", "unknown")


@dataclass(frozen=True)
class RegimeResult:
    """The classified regime plus optional metadata flags.

    `fast_resolve` is True when a high-B segment is loosening very
    quickly (methodology §7.6 edge case 2). The scoreboard uses
    it to add a tooltip warning; the regime label itself stays
    RESOLVING.
    """

    regime: Regime
    fast_resolve: bool = False


def _cell_match(b: float, bp: float, cell: dict) -> bool:
    """Test whether (b, bp) falls in this cell.

    Convention: `b_min` and `b_prime_min` are inclusive lower bounds.
    `b_max` and `b_prime_max` are exclusive upper bounds by default;
    set `b_prime_max_inclusive: true` (or `b_max_inclusive: true`)
    to flip a max bound to inclusive. This handles the spec's
    `B' <= -15` style lower cells without ambiguity.
    """
    if "b_min" in cell and b < cell["b_min"]:
        return False
    if "b_max" in cell:
        if cell.get("b_max_inclusive", False):
            if b > cell["b_max"]:
                return False
        else:
            if b >= cell["b_max"]:
                return False
    bp_min = cell.get("b_prime_min")
    bp_max = cell.get("b_prime_max")
    if bp_min is not None and bp < bp_min:
        return False
    if bp_max is not None:
        if cell.get("b_prime_max_inclusive", False):
            if bp > bp_max:
                return False
        else:
            if bp >= bp_max:
                return False
    return True


def _classify_from_thresholds(b: float, bp: float) -> tuple[Regime, bool]:
    """Walk the configured cells in order; first match wins.

    The cell order in the JSON is the order of the 6 cells in the
    plan §7.6 (B >= 70 first, B < 70 second), with the B < 70
    cells in descending regime severity. The JSON keeps this
    ordering; if you reorder it, re-run the boundary tests in
    `test_score_regime.py`.
    """
    fast_resolve = False
    for cell in _THRESHOLDS["cells"]:
        if _cell_match(b, bp, cell):
            regime = Regime(cell["regime"])
            if regime == Regime.RESOLVING and bp < FAST_RESOLVE_THRESHOLD:
                fast_resolve = True
            return regime, fast_resolve
    # No cell matched — config is incomplete. Fall back to STABLE
    # so the scoreboard still renders something rather than crash.
    _LOGGER.warning(
        "no regime cell matched (b=%s, bp=%s); falling back to STABLE. Check research/06_regime_thresholds.json.",
        b,
        bp,
    )
    return Regime.STABLE, False


def classify(
    score: float | None,
    momentum: float | None,
    data_completeness: float,
) -> RegimeResult:
    """Map (B, B', data_completeness) to a regime per §7.6.

    `score` and `momentum` are None for segments with no data;
    the data_completeness gate short-circuits to NO_DATA before
    the 6-cell table is consulted.
    """
    if data_completeness < NO_DATA_THRESHOLD or score is None or momentum is None:
        return RegimeResult(regime=Regime.NO_DATA)
    regime, fast_resolve = _classify_from_thresholds(score, momentum)
    return RegimeResult(regime=regime, fast_resolve=fast_resolve)
