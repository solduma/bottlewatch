"""Tests for app/score/normalize.py."""

from __future__ import annotations

from bottlewatch.app.score.normalize import (
    history_is_mature_dated,
    normalize_5y,
)


def test_normalize_midpoint_returns_half() -> None:
    assert normalize_5y(50.0, [0.0, 100.0]) == 0.5


def test_normalize_at_min_returns_zero() -> None:
    assert normalize_5y(0.0, [0.0, 50.0, 100.0]) == 0.0


def test_normalize_at_max_returns_one() -> None:
    assert normalize_5y(100.0, [0.0, 50.0, 100.0]) == 1.0


def test_normalize_clamps_above_max() -> None:
    # New high sets the band; clamp at 1.0 instead of overflowing.
    assert normalize_5y(150.0, [0.0, 50.0, 100.0]) == 1.0


def test_normalize_clamps_below_min() -> None:
    assert normalize_5y(-10.0, [0.0, 50.0, 100.0]) == 0.0


def test_normalize_flat_history_returns_half() -> None:
    # min == max → no signal → methodology §1 default 0.5
    assert normalize_5y(42.0, [5.0, 5.0, 5.0]) == 0.5


def test_normalize_empty_history_returns_half() -> None:
    # methodology §1: <2 years of history → median
    assert normalize_5y(42.0, []) == 0.5


def test_history_is_mature_true_for_2y_span() -> None:
    # 730 days exactly = mature (>= boundary)
    history = [(0.0, 1.0), (730 * 86_400, 2.0)]
    assert history_is_mature_dated(history) is True


def test_history_is_mature_false_for_short_span() -> None:
    history = [(0.0, 1.0), (100 * 86_400, 2.0)]
    assert history_is_mature_dated(history) is False


def test_history_is_mature_false_for_single_point() -> None:
    assert history_is_mature_dated([(0.0, 1.0)]) is False
