"""Tests for app/score/normalize.py."""

from __future__ import annotations

from bottlewatch.app.score.normalize import (
    history_is_mature,
    normalize_5y,
    normalize_subscore,
)


# ---------------------------------------------------------------------------
# normalize_5y (rolling band helper)
# ---------------------------------------------------------------------------


def test_normalize_midpoint_returns_half() -> None:
    assert normalize_5y(50.0, [0.0, 100.0]) == 0.5


def test_normalize_at_min_returns_zero() -> None:
    assert normalize_5y(0.0, [0.0, 50.0, 100.0]) == 0.0


def test_normalize_at_max_returns_one() -> None:
    assert normalize_5y(100.0, [0.0, 50.0, 100.0]) == 1.0


def test_normalize_clamps_above_max() -> None:
    assert normalize_5y(150.0, [0.0, 50.0, 100.0]) == 1.0


def test_normalize_clamps_below_min() -> None:
    assert normalize_5y(-10.0, [0.0, 50.0, 100.0]) == 0.0


def test_normalize_flat_history_returns_half() -> None:
    assert normalize_5y(42.0, [5.0, 5.0, 5.0]) == 0.5


def test_normalize_empty_history_returns_half() -> None:
    assert normalize_5y(42.0, []) == 0.5


def test_history_is_mature_true_for_2y_span() -> None:
    history = [(0.0, 1.0), (730 * 86_400, 2.0)]
    assert history_is_mature(history) is True


def test_history_is_mature_false_for_short_span() -> None:
    history = [(0.0, 1.0), (100 * 86_400, 2.0)]
    assert history_is_mature(history) is False


def test_history_is_mature_false_for_single_point() -> None:
    assert history_is_mature([(0.0, 1.0)]) is False


# ---------------------------------------------------------------------------
# normalize_subscore (fixed + rolling + imputation)
# ---------------------------------------------------------------------------


def test_fixed_band_maps_transformer_ppi() -> None:
    result = normalize_subscore("lead_time_growth", 215.0, "transformers_ppi", "fixed")
    assert result.value == 0.5
    assert result.source == "extractor"
    assert result.normalization_mode == "fixed"
    assert result.band_min == 80.0
    assert result.band_max == 350.0


def test_fixed_band_clamps_outside() -> None:
    result = normalize_subscore("lead_time_growth", 500.0, "transformers_ppi", "fixed")
    assert result.value == 1.0


def test_seed_passthrough() -> None:
    result = normalize_subscore("lead_time_growth", 0.75, "seed", "fixed")
    assert result.value == 0.75
    assert result.source == "seed"
    assert result.confidence == "low"


def test_none_input_is_imputed() -> None:
    result = normalize_subscore("capacity_tightness", None, "power_ratio", "fixed")
    assert result.value == 0.5
    assert result.source == "imputed"
    assert result.imputed is True
    assert result.confidence == "low"


def test_rolling_mode_with_mature_history() -> None:
    # Two years (730 days) of history, values 0..100. Use timestamps
    # that span exactly 730 days so the maturity gate is satisfied.
    history = [(i * 86_400.0, float(i)) for i in range(731)]
    result = normalize_subscore("lead_time_growth", 365.0, "transformers_ppi", "rolling", history=history)
    assert result.normalization_mode == "rolling"
    assert result.source == "extractor"
    assert result.confidence == "high"


def test_rolling_mode_falls_back_when_history_short() -> None:
    history = [(0.0, 80.0), (100 * 86_400, 350.0)]
    result = normalize_subscore("lead_time_growth", 215.0, "transformers_ppi", "rolling", history=history)
    assert result.normalization_mode == "fallback_to_fixed"
    assert result.value == 0.5


def test_rolling_mode_medium_confidence_for_1y_history() -> None:
    # History spanning exactly 1 year (365 days).
    history = [(i * 86_400.0, float(i)) for i in range(366)]
    result = normalize_subscore("lead_time_growth", 180.0, "transformers_ppi", "rolling", history=history)
    assert result.confidence == "medium"
