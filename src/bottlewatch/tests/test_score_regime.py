"""Tests for app/score/regime.py.

One test per cell of the §7.6 table, plus the NO_DATA gate, plus
a regression test pinning the JSON-driven calibration so a
recalibration is a conscious change.
"""

from __future__ import annotations


import pytest

from bottlewatch.app.score.regime import (
    FAST_RESOLVE_THRESHOLD,
    NO_DATA_THRESHOLD,
    B_THRESHOLD,
    _THRESHOLDS_VERSION,
    Regime,
    classify,
)


def test_peaking() -> None:
    # B >= 70, B' >= +20
    r = classify(score=80, momentum=+25, data_completeness=1.0)
    assert r.regime is Regime.PEAKING
    assert r.fast_resolve is False


def test_peaked() -> None:
    # B >= 70, 0 <= B' < 20
    r = classify(score=75, momentum=+10, data_completeness=1.0)
    assert r.regime is Regime.PEAKED


def test_resolving() -> None:
    # B >= 70, B' < 0 (not fast)
    r = classify(score=80, momentum=-10, data_completeness=1.0)
    assert r.regime is Regime.RESOLVING
    assert r.fast_resolve is False


def test_resolving_fast_resolve() -> None:
    # B >= 70, B' < FAST_RESOLVE_THRESHOLD
    r = classify(score=80, momentum=FAST_RESOLVE_THRESHOLD - 1, data_completeness=1.0)
    assert r.regime is Regime.RESOLVING
    assert r.fast_resolve is True


def test_emerging() -> None:
    # B < 70, B' >= +30
    r = classify(score=50, momentum=+35, data_completeness=1.0)
    assert r.regime is Regime.EMERGING


def test_stable() -> None:
    # 30 <= B < 70, -15 <= B' < +30
    r = classify(score=50, momentum=0, data_completeness=1.0)
    assert r.regime is Regime.STABLE


def test_resolving_from_low() -> None:
    # B < 30, B' <= -15
    r = classify(score=20, momentum=-20, data_completeness=1.0)
    assert r.regime is Regime.RESOLVING_FROM_LOW


def test_no_data_below_completeness_threshold() -> None:
    r = classify(score=80, momentum=+30, data_completeness=0.3)
    assert r.regime is Regime.NO_DATA


def test_no_data_when_score_is_none() -> None:
    r = classify(score=None, momentum=None, data_completeness=0.8)
    assert r.regime is Regime.NO_DATA


@pytest.mark.parametrize(
    "score, momentum, expected",
    [
        (80, +25, Regime.PEAKING),
        (75, +10, Regime.PEAKED),
        (80, -10, Regime.RESOLVING),
        (50, +35, Regime.EMERGING),
        (50, 0, Regime.STABLE),
        (20, -20, Regime.RESOLVING_FROM_LOW),
    ],
)
def test_table_driven(score: float, momentum: float, expected: Regime) -> None:
    r = classify(score=score, momentum=momentum, data_completeness=1.0)
    assert r.regime is expected


# ---------------------------------------------------------------------------
# JSON calibration pinning
# ---------------------------------------------------------------------------


def test_thresholds_file_loads_with_expected_version() -> None:
    """Pins the calibration version. If you recalibrate, bump
    `version` in research/06_regime_thresholds.json AND update
    this test — that double-keyed lock is the cost of a JSON
    config you can edit without re-deploying Python."""
    assert _THRESHOLDS_VERSION == "M2-v1"


def test_thresholds_file_has_all_seven_cells() -> None:
    """All 7 cells (6 plan cells + NO_DATA gate) must be present
    in the JSON. The classifier walks them in order; a missing
    cell silently falls through to STABLE."""
    expected_cells = {
        "PEAKING",
        "PEAKED",
        "RESOLVING",
        "EMERGING",
        "STABLE",
        "RESOLVING_FROM_LOW",
    }
    from bottlewatch.app.score.regime import _THRESHOLDS  # noqa: PLC0415

    regimes_in_file = {c["regime"] for c in _THRESHOLDS["cells"]}
    assert regimes_in_file == expected_cells


def test_b_threshold_matches_plan_m2_calibration() -> None:
    """B threshold is 70 in M2. If the spec reverts to 60 (the
    original plan placeholder), this test fires."""
    assert B_THRESHOLD == 70
    assert NO_DATA_THRESHOLD == 0.4
    assert FAST_RESOLVE_THRESHOLD == -50.0


def test_classify_runs_against_published_calibration() -> None:
    """Cross-checks the configured cells with classify(). A
    boundary pair at the edge of every cell must produce the
    regime the cell declares."""
    boundary_pairs = [
        # (b, b', expected)
        (70, +20, Regime.PEAKING),  # lower bound of PEAKING
        (70, 0, Regime.PEAKED),  # lower bound of PEAKED (B'=0)
        (70, -1, Regime.RESOLVING),  # just below PEAKED
        (69, +30, Regime.EMERGING),  # just below B threshold
        (30, -15, Regime.STABLE),  # RESOLVING_FROM_LOW lower bound
        (29, -15, Regime.RESOLVING_FROM_LOW),  # B < 30
    ]
    for b, bp, expected in boundary_pairs:
        r = classify(score=b, momentum=bp, data_completeness=1.0)
        assert r.regime is expected, f"({b}, {bp}) -> {r.regime}, expected {expected}"
