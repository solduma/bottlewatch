"""Tests for backtest statistics helpers."""

from __future__ import annotations

from datetime import date

import pytest

from bottlewatch.app.backtest.stats import benjamini_hochberg, segment_ic_with_ci


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


def test_segment_ic_with_ci_perfect_correlation() -> None:
    xs = list(range(10))
    ys = list(range(10))
    dates = [date(2025, 1, 1) + __import__("datetime").timedelta(days=i) for i in range(10)]
    points_by_date = {d: [(float(x), float(y))] for d, x, y in zip(dates, xs, ys)}
    result = segment_ic_with_ci("seg_a", xs, ys, dates, points_by_date)
    assert result.rho == pytest.approx(1.0, abs=1e-6)
    assert result.p_value is not None
    assert result.p_value < 0.01
    assert result.ci_low is not None
    assert result.ci_high is not None


def test_segment_ic_with_ci_short_history_returns_none() -> None:
    result = segment_ic_with_ci("seg_a", [1.0, 2.0], [3.0, 4.0], [], {})
    assert result.rho == 0.0
    assert result.p_value is None
    assert result.ci_low is None
