"""Tests for the hyperscaler AI capex ledger loader and extractor."""

from __future__ import annotations

import json

import pytest

from bottlewatch.app.score.capex_ledger import Ledger, load_ledger, series_for_segment
from bottlewatch.app.score.extractors import _hyperscaler_demand_signal


def _make_ledger(yoy: float) -> Ledger:
    """Build a minimal ledger with 5 quarters of aggregate capex.

    `yoy` is the desired trailing-4Q vs prior-4Q growth. The first 4
    quarters are a base value, the 5th quarter is base * (1 + 4*yoy),
    so the YoY is exactly `yoy`.
    """
    base = 100.0
    values = [base] * 4 + [base * (1.0 + 4.0 * yoy)]
    return {
        "data_center_shell": {
            "signal_name": "hyperscaler_ai_capex",
            "unit": "USD_B",
            "entries": [
                {"ticker": "MSFT", "fiscal_quarter": f"2024-Q{i + 1}", "ai_capex_usd_b": v, "source": "test"}
                for i, v in enumerate(values)
            ],
        }
    }


def test_load_ledger_reads_json(tmp_path) -> None:
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps({"data_center_shell": {"signal_name": "x", "unit": "USD_B", "entries": []}}))
    ledger = load_ledger(path)
    assert "data_center_shell" in ledger
    assert "_comment" not in ledger


def test_series_aggregates_by_quarter() -> None:
    ledger: Ledger = {
        "data_center_shell": {
            "signal_name": "hyperscaler_ai_capex",
            "unit": "USD_B",
            "entries": [
                {"ticker": "MSFT", "fiscal_quarter": "2025-Q1", "ai_capex_usd_b": 10.0, "source": "test"},
                {"ticker": "GOOG", "fiscal_quarter": "2025-Q1", "ai_capex_usd_b": 8.0, "source": "test"},
                {"ticker": "MSFT", "fiscal_quarter": "2025-Q2", "ai_capex_usd_b": 12.0, "source": "test"},
            ],
        }
    }
    series = series_for_segment("data_center_shell", ledger)
    assert series is not None
    assert series.values == [18.0, 12.0]
    assert series.source_count == 2


def test_hyperscaler_demand_signal_returns_none_for_short_series() -> None:
    ledger: Ledger = {
        "data_center_shell": {
            "signal_name": "hyperscaler_ai_capex",
            "unit": "USD_B",
            "entries": [
                {"ticker": "MSFT", "fiscal_quarter": "2025-Q1", "ai_capex_usd_b": 10.0, "source": "test"},
            ],
        }
    }
    assert _hyperscaler_demand_signal("data_center_shell", ledger) is None


def test_hyperscaler_demand_signal_returns_raw_yoy() -> None:
    ledger = _make_ledger(0.30)  # +30% YoY
    # The extractor now returns the raw YoY ratio; normalization happens later.
    assert _hyperscaler_demand_signal("data_center_shell", ledger) == pytest.approx(0.30)


def test_hyperscaler_demand_signal_returns_high_raw_yoy() -> None:
    ledger = _make_ledger(0.60)  # +60% YoY
    assert _hyperscaler_demand_signal("data_center_shell", ledger) == pytest.approx(0.60)


def test_hyperscaler_demand_signal_returns_negative_raw_yoy() -> None:
    ledger = _make_ledger(-0.30)  # -30% YoY
    assert _hyperscaler_demand_signal("data_center_shell", ledger) == pytest.approx(-0.30)


def test_hyperscaler_demand_signal_follows_entries_ref_raw() -> None:
    ledger = _make_ledger(0.30)
    ledger["gpu_asic_silicon"] = {
        "signal_name": "hyperscaler_ai_capex",
        "unit": "USD_B",
        "entries_ref": "data_center_shell",
    }
    assert _hyperscaler_demand_signal("gpu_asic_silicon", ledger) == pytest.approx(0.30)


def test_hyperscaler_demand_signal_returns_none_for_missing_segment() -> None:
    ledger = _make_ledger(0.30)
    assert _hyperscaler_demand_signal("not_a_segment", ledger) is None
