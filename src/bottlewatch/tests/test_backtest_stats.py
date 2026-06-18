"""Tests for backtest statistics helpers (date-level bootstrap inference)."""

from __future__ import annotations

import math
from datetime import date, timedelta

from bottlewatch.app.backtest.stats import (
    benjamini_hochberg,
    block_size_for,
    date_level_ic,
    segment_ic_with_ci,
)


def _dates(n: int) -> list[date]:
    return [date(2025, 1, 1) + timedelta(days=30 * i) for i in range(n)]


def _monotonic_points_by_date(dates: list[date], n_per_date: int = 6) -> dict[date, list[tuple[float, float]]]:
    """Each date: a perfectly monotonic B->return relationship."""
    return {d: [(float(j), float(j)) for j in range(n_per_date)] for d in dates}


def _noise_points_by_date(dates: list[date], n_per_date: int = 8) -> dict[date, list[tuple[float, float]]]:
    """Alternating dates correlate +1 / -1 → mean IC ~ 0, CI spanning 0."""
    out: dict[date, list[tuple[float, float]]] = {}
    for i, d in enumerate(dates):
        if i % 2 == 0:
            out[d] = [(float(j), float(j)) for j in range(n_per_date)]
        else:
            out[d] = [(float(j), float(n_per_date - 1 - j)) for j in range(n_per_date)]
    return out


# ---------------------------------------------------------------------------
# Benjamini-Hochberg (unchanged behavior)
# ---------------------------------------------------------------------------


def test_benjamini_hochberg_rejects_strong_signals() -> None:
    p_values = [
        ("seg_a", 0.01),
        ("seg_b", 0.04),
        ("seg_c", 0.20),
        ("seg_d", 0.50),
    ]
    rejected = benjamini_hochberg(p_values, alpha=0.10)
    assert rejected["seg_a"] is True
    assert rejected["seg_b"] is True
    assert rejected["seg_c"] is False
    assert rejected["seg_d"] is False


def test_benjamini_hochberg_handles_none_p_values() -> None:
    p_values = [
        ("seg_a", None),
        ("seg_b", 0.05),
    ]
    rejected = benjamini_hochberg(p_values, alpha=0.10)
    assert rejected["seg_a"] is False
    assert rejected["seg_b"] is True


def test_benjamini_hochberg_empty() -> None:
    assert benjamini_hochberg([]) == {}


# ---------------------------------------------------------------------------
# Property 1: consistency — ci_low <= rho <= ci_high
# ---------------------------------------------------------------------------


def test_property_consistency_point_estimate_inside_ci() -> None:
    dates = _dates(10)
    pbd = _monotonic_points_by_date(dates)
    result = segment_ic_with_ci("seg", 60, dates, pbd, forward_days=90, step_days=30)
    assert result.rho is not None
    assert result.ci_low is not None
    assert result.ci_high is not None
    assert result.ci_low <= result.rho <= result.ci_high


# ---------------------------------------------------------------------------
# Property 2: pseudo-replication fixed — duplicating tickers within a date
# leaves the date-level IC, CI width, and p-value unchanged.
# ---------------------------------------------------------------------------


def test_property_pseudo_replication_fixed() -> None:
    dates = _dates(10)
    base = _monotonic_points_by_date(dates, n_per_date=6)
    duplicated = {d: pts + pts for d, pts in base.items()}  # 2x correlated rows per date

    r_base = date_level_ic(dates, base, forward_days=90, step_days=30)
    r_dup = date_level_ic(dates, duplicated, forward_days=90, step_days=30)

    assert r_base.mean is not None and r_dup.mean is not None
    assert r_base.mean == r_dup.mean  # per-date Spearman is invariant to row duplication
    assert r_base.ci_low == r_dup.ci_low
    assert r_base.ci_high == r_dup.ci_high
    assert r_base.p_value == r_dup.p_value


# ---------------------------------------------------------------------------
# Property 3: block_size derivation
# ---------------------------------------------------------------------------


def test_property_block_size_derivation() -> None:
    assert block_size_for(90, 30) == math.ceil(90 / 30) == 3
    assert block_size_for(60, 30) == math.ceil(60 / 30) == 2
    assert block_size_for(45, 30) == math.ceil(45 / 30) == 2
    assert block_size_for(30, 30) == 1
    assert block_size_for(10, 30) == 1  # floored at 1


# ---------------------------------------------------------------------------
# Property 4: p-value sanity
# ---------------------------------------------------------------------------


def test_property_p_value_sanity_perfect_signal() -> None:
    dates = _dates(10)
    pbd = _monotonic_points_by_date(dates)
    r = date_level_ic(dates, pbd, forward_days=90, step_days=30)
    assert r.mean is not None
    assert r.mean > 0.99
    assert r.p_value is not None
    assert r.p_value < 0.05
    assert r.ci_low is not None and r.ci_low > 0.0  # CI excludes 0


def test_property_p_value_sanity_pure_noise() -> None:
    dates = _dates(12)
    pbd = _noise_points_by_date(dates)
    r = date_level_ic(dates, pbd, forward_days=90, step_days=30)
    assert r.mean is not None
    assert abs(r.mean) < 0.2
    assert r.p_value is not None
    assert r.p_value > 0.30
    assert r.ci_low is not None and r.ci_high is not None
    assert r.ci_low < 0.0 < r.ci_high  # CI spans 0


# ---------------------------------------------------------------------------
# Property 6: determinism (property 5 is asserted in test_backtest.py)
# ---------------------------------------------------------------------------


def test_property_determinism() -> None:
    dates = _dates(10)
    pbd = _monotonic_points_by_date(dates)
    r1 = date_level_ic(dates, pbd, forward_days=90, step_days=30)
    r2 = date_level_ic(dates, pbd, forward_days=90, step_days=30)
    assert r1 == r2


# ---------------------------------------------------------------------------
# Behavioral contract: < 2 usable eval dates → all None
# ---------------------------------------------------------------------------


def test_fewer_than_two_dates_returns_none() -> None:
    dates = _dates(1)
    pbd = _monotonic_points_by_date(dates)
    result = segment_ic_with_ci("seg", 6, dates, pbd, forward_days=90, step_days=30)
    assert result.rho is None
    assert result.p_value is None
    assert result.ci_low is None
    assert result.ci_high is None


def test_degenerate_dates_skipped_then_too_few() -> None:
    dates = _dates(5)
    # Only one date has >=4 varying points; the rest are degenerate.
    pbd: dict[date, list[tuple[float, float]]] = {dates[0]: [(float(j), float(j)) for j in range(6)]}
    for d in dates[1:]:
        pbd[d] = [(1.0, 1.0), (1.0, 1.0)]  # < 4 points / no variance
    result = date_level_ic(dates, pbd, forward_days=90, step_days=30)
    assert result.n_dates == 1
    assert result.mean is None
    assert result.p_value is None
