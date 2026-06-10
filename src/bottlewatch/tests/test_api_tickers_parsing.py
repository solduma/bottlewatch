"""Unit tests for the float-parsing helpers in app/api/tickers.py."""

from __future__ import annotations

import pytest

from bottlewatch.app.api.tickers import _coerce_float, _parse_exposure_pct, _pick_eta


def test_coerce_float_parses_normal_number() -> None:
    assert _coerce_float("42.5") == 42.5
    assert _coerce_float("0") == 0.0
    assert _coerce_float("  10  ") == 10.0


def test_coerce_float_strips_dollar_and_comma() -> None:
    assert _coerce_float("$1,234.56") == 1234.56


def test_coerce_float_returns_none_on_empty() -> None:
    assert _coerce_float("") is None
    assert _coerce_float("   ") is None


def test_coerce_float_raises_on_garbage() -> None:
    """Regression: garbage used to silently become 0.0; now it raises
    so the caller can decide between None (missing) and 0.0 (zero)."""
    with pytest.raises(ValueError):
        _coerce_float("n/a")
    with pytest.raises(ValueError):
        _coerce_float("TBD")


def test_parse_exposure_pct_returns_none_for_missing() -> None:
    assert _parse_exposure_pct({"exposure_pct": ""}, ticker="X", segment="y") is None


def test_parse_exposure_pct_warns_and_returns_none_for_garbage(caplog) -> None:
    import logging

    with caplog.at_level(logging.WARNING, logger="bottlewatch.app.api.tickers"):
        out = _parse_exposure_pct({"exposure_pct": "n/a"}, ticker="X", segment="y")
    assert out is None
    assert "unparseable exposure_pct" in caplog.text
    assert "X" in caplog.text
    assert "y" in caplog.text


def test_parse_exposure_pct_parses_valid() -> None:
    assert _parse_exposure_pct({"exposure_pct": "75"}, ticker="X", segment="y") == 75.0


# ---------------------------------------------------------------------------
# _pick_eta
# ---------------------------------------------------------------------------


_STATIC_ETA = {
    "transformers_tnd": (">24mo", "high"),
    "power_generation_oem": (">24mo", "medium"),
    "hbm_memory": ("12-24mo", "medium"),
}


def test_pick_eta_returns_none_for_empty_segment_map() -> None:
    assert _pick_eta({}, _STATIC_ETA) is None


def test_pick_eta_picks_highest_exposure_segment() -> None:
    """Regression: previously picked `next(iter(segment_map))` which
    depended on dict insertion order; for multi-segment tickers the
    result was non-deterministic."""
    seg_map = {
        "hbm_memory": {"exposure_pct": 10.0},
        "transformers_tnd": {"exposure_pct": 80.0},
        "power_generation_oem": {"exposure_pct": 30.0},
    }
    eta = _pick_eta(seg_map, _STATIC_ETA)
    assert eta == {"eta": ">24mo", "confidence": "high", "segment": "transformers_tnd"}


def test_pick_eta_breaks_ties_by_first_seen() -> None:
    seg_map = {
        "hbm_memory": {"exposure_pct": 50.0},
        "transformers_tnd": {"exposure_pct": 50.0},
    }
    eta = _pick_eta(seg_map, _STATIC_ETA)
    # hbm_memory was inserted first; ties go to first-seen.
    assert eta == {"eta": "12-24mo", "confidence": "medium", "segment": "hbm_memory"}


def test_pick_eta_treats_none_as_lower_than_zero() -> None:
    seg_map = {
        "hbm_memory": {"exposure_pct": None},
        "transformers_tnd": {"exposure_pct": 0.0},
    }
    eta = _pick_eta(seg_map, _STATIC_ETA)
    assert eta["segment"] == "transformers_tnd"


def test_pick_eta_returns_none_if_no_segment_in_table() -> None:
    seg_map = {
        "unknown_segment": {"exposure_pct": 100.0},
    }
    assert _pick_eta(seg_map, _STATIC_ETA) is None
