"""Tests for app/score/extractors.py — the per-segment raw extractors.

These are pure unit tests: we pass in plain `_Row`-shaped objects and
assert the raw metric value and source key. Normalization to [0, 1] is
tested separately in test_score_normalize.py.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

import pytest

from bottlewatch.app.score.extractors import (
    ExtractorResult,
    _hhi_from_counts,
    capacity_tightness,
    demand_signal,
    geo_concentration,
    lead_time_growth,
)


@dataclass(frozen=True)
class _Row:
    signal_name: str
    value_num: Optional[float]
    observed_at: date


def _add_months(d: date, n: int) -> date:
    """Add n months to a date, handling year rollover."""
    year = d.year + (d.month - 1 + n) // 12
    month = (d.month - 1 + n) % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))


# ---------------------------------------------------------------------------
# capacity_tightness
# ---------------------------------------------------------------------------


def test_power_combines_forward_and_operating() -> None:
    signals = [
        _Row("planned_capacity_mw", 2000.0, date(2027, 1, 1)),
        _Row("planned_capacity_mw", 3000.0, date(2027, 6, 1)),
        _Row("capacity_mw", 20000.0, date(2025, 1, 1)),
    ]
    result = capacity_tightness("power_generation_oem", signals)
    assert isinstance(result, ExtractorResult)
    assert result.raw_value == pytest.approx(0.25)
    assert result.source_key == "power_ratio"


def test_power_returns_none_without_capacity_signal() -> None:
    signals = [_Row("planned_capacity_mw", 100.0, date(2027, 1, 1))]
    assert capacity_tightness("power_generation_oem", signals) is None


def test_power_returns_none_without_planned_signal() -> None:
    signals = [_Row("capacity_mw", 20000.0, date(2025, 1, 1))]
    assert capacity_tightness("power_generation_oem", signals) is None


def test_data_center_shell_returns_raw_yoy() -> None:
    signals = []
    for m in range(1, 25):
        val = 1000.0 if m <= 12 else 1200.0
        signals.append(
            _Row(
                "retail_sales_mwh",
                val,
                date(2024, m, 1) if m <= 12 else date(2025, m - 12, 1),
            )
        )
    result = capacity_tightness("data_center_shell", signals)
    assert isinstance(result, ExtractorResult)
    assert result.raw_value == pytest.approx(0.20, abs=1e-3)
    assert result.source_key == "retail_sales_yoy"


def test_data_center_shell_returns_none_for_short_history() -> None:
    signals = [_Row("retail_sales_mwh", 1000.0, date(2025, m, 1)) for m in range(1, 13)]
    assert capacity_tightness("data_center_shell", signals) is None


def test_unknown_segment_returns_none() -> None:
    signals = [_Row("capacity_mw", 100.0, date(2025, 1, 1))]
    assert capacity_tightness("cooling_water", signals) is None


def test_empty_signals_returns_none() -> None:
    assert capacity_tightness("power_generation_oem", []) is None


# ---------------------------------------------------------------------------
# SEC EDGAR keyword extractors
# ---------------------------------------------------------------------------


def test_edgar_lead_time_growth_uses_mentions() -> None:
    signals = []
    base = date(2025, 1, 1)
    for i in range(11):
        signals.append(_Row("lead_time_mentions", 2.0, _add_months(base, i)))
    signals.append(_Row("lead_time_mentions", 20.0, _add_months(base, 11)))
    result = lead_time_growth("advanced_node_fabs", signals)
    assert isinstance(result, ExtractorResult)
    assert result.raw_value is not None
    assert result.raw_value > 0.0
    assert result.source_key == "edgar_keyword"


def test_edgar_capacity_tightness_uses_shortage_and_expansion() -> None:
    signals = []
    base = date(2025, 1, 1)
    for i in range(11):
        signals.append(_Row("shortage_mentions", 1.0, _add_months(base, i)))
        signals.append(_Row("capacity_expansion_mentions", 1.0, _add_months(base, i)))
    signals.append(_Row("shortage_mentions", 10.0, _add_months(base, 11)))
    result = capacity_tightness("power_generation_oem", signals)
    assert isinstance(result, ExtractorResult)
    assert result.raw_value is not None
    assert result.raw_value > 0.0
    assert result.source_key == "edgar_keyword"


def test_edgar_keyword_score_returns_none_for_short_history() -> None:
    base = date(2025, 1, 1)
    signals = [_Row("lead_time_mentions", 5.0, _add_months(base, i)) for i in range(5)]
    assert lead_time_growth("advanced_node_fabs", signals) is None


# ---------------------------------------------------------------------------
# Comtrade trade-volume capacity tightness
# ---------------------------------------------------------------------------


def test_comtrade_capacity_tightness_uses_yoy_growth() -> None:
    base = date(2025, 1, 1)
    signals = [_Row("trade_volume", 100.0, base)]
    for i in range(12):
        v = 100.0 + ((i + 1) * (140 - 100) / 12)
        signals.append(_Row("trade_volume", v, _add_months(base, i + 1)))
    for segment in ("hbm_memory", "advanced_packaging", "transformers_tnd"):
        result = capacity_tightness(segment, signals)
        assert isinstance(result, ExtractorResult)
        assert result.raw_value == pytest.approx(0.40)
        assert result.source_key == "comtrade_volume"


def test_comtrade_capacity_tightness_returns_none_for_short_history() -> None:
    signals = [_Row("trade_volume", 100.0, date(2025, m, 1)) for m in range(1, 13)]
    assert capacity_tightness("advanced_packaging", signals) is None


def test_comtrade_capacity_tightness_returns_none_for_unmapped_segment() -> None:
    signals = [_Row("trade_volume", 100.0, date(2025, 1, 1))]
    assert capacity_tightness("cooling_water", signals) is None


# ---------------------------------------------------------------------------
# transformers_tnd demand_signal
# ---------------------------------------------------------------------------


def test_transformer_demand_signal_returns_raw_yoy() -> None:
    base = date(2025, 1, 1)
    signals = [_Row("electrical_equipment_orders", 80.0, base)]
    for i in range(12):
        v = 80.0 + ((i + 1) * (100 - 80) / 12)
        signals.append(_Row("electrical_equipment_orders", v, _add_months(base, i + 1)))
    result = demand_signal("transformers_tnd", signals)
    assert isinstance(result, ExtractorResult)
    assert result.raw_value == pytest.approx(0.25)
    assert result.source_key == "transformer_orders"


def test_transformer_demand_signal_returns_none_for_short_history() -> None:
    base = date(2025, 1, 1)
    signals = [_Row("electrical_equipment_orders", 100.0, _add_months(base, i)) for i in range(6)]
    assert demand_signal("transformers_tnd", signals) is None


def test_unknown_segment_demand_signal_returns_none() -> None:
    base = date(2025, 1, 1)
    signals = [_Row("electrical_equipment_orders", 100.0, _add_months(base, i)) for i in range(13)]
    assert demand_signal("cooling_water", signals) is None


# ---------------------------------------------------------------------------
# transformers_tnd lead_time_growth
# ---------------------------------------------------------------------------


def test_transformer_lead_time_growth_returns_raw_ppi() -> None:
    base = date(2025, 1, 1)
    signals = [_Row("ppi_transformers", 215.0, _add_months(base, i)) for i in range(2)]
    result = lead_time_growth("transformers_tnd", signals)
    assert isinstance(result, ExtractorResult)
    assert result.raw_value == pytest.approx(215.0)
    assert result.source_key == "transformers_ppi"


def test_transformer_lead_time_growth_uses_latest_observation() -> None:
    signals = [
        _Row("ppi_transformers", 80.0, date(2024, 1, 1)),
        _Row("ppi_transformers", 150.0, date(2024, 6, 1)),
        _Row("ppi_transformers", 280.0, date(2025, 1, 1)),
    ]
    result = lead_time_growth("transformers_tnd", signals)
    assert isinstance(result, ExtractorResult)
    assert result.raw_value == pytest.approx(280.0)


def test_transformer_lead_time_growth_returns_none_for_short_history() -> None:
    base = date(2025, 1, 1)
    signals = [_Row("ppi_transformers", 215.0, base)]
    assert lead_time_growth("transformers_tnd", signals) is None


def test_unknown_segment_lead_time_growth_returns_none() -> None:
    base = date(2025, 1, 1)
    signals = [_Row("ppi_transformers", 250.0, _add_months(base, i)) for i in range(2)]
    assert lead_time_growth("cooling_water", signals) is None
    assert lead_time_growth("data_center_shell", signals) is None


# ---------------------------------------------------------------------------
# Phase 1 cross-segment FRED proxies
# ---------------------------------------------------------------------------


def test_semi_lead_time_growth_returns_raw_ppi_semis_yoy() -> None:
    base = date(2025, 1, 1)
    signals = [_Row("ppi_semis", 100.0, base)]
    for i in range(12):
        v = 100.0 + ((i + 1) * (125 - 100) / 12)
        signals.append(_Row("ppi_semis", v, _add_months(base, i + 1)))
    for segment in (
        "advanced_node_fabs",
        "hbm_memory",
        "gpu_asic_silicon",
        "networking_interconnect",
        "advanced_packaging",
    ):
        result = lead_time_growth(segment, signals)
        assert isinstance(result, ExtractorResult)
        assert result.raw_value == pytest.approx(0.25)
        assert result.source_key == "semi_ppi"


def test_semi_lead_time_growth_returns_none_for_short_history() -> None:
    base = date(2025, 1, 1)
    signals = [_Row("ppi_semis", 100.0, _add_months(base, i)) for i in range(6)]
    assert lead_time_growth("advanced_node_fabs", signals) is None


def test_manufacturing_demand_signal_returns_raw_indpro_yoy() -> None:
    base = date(2025, 1, 1)
    signals = [_Row("industrial_production", 100.0, base)]
    for i in range(12):
        v = 100.0 + ((i + 1) * (110 - 100) / 12)
        signals.append(_Row("industrial_production", v, _add_months(base, i + 1)))
    for segment in ("systems_rack_scale", "cooling_water", "power_generation_oem"):
        result = demand_signal(segment, signals)
        assert isinstance(result, ExtractorResult)
        assert result.raw_value == pytest.approx(0.10)
        assert result.source_key == "manufacturing_indpro"


def test_manufacturing_capacity_tightness_returns_raw_tcu() -> None:
    signals = [_Row("capacity_utilization", 85.0, date(2025, 1, 1))]
    for segment in ("systems_rack_scale", "cooling_water"):
        result = capacity_tightness(segment, signals)
        assert isinstance(result, ExtractorResult)
        assert result.raw_value == pytest.approx(85.0)
        assert result.source_key == "manufacturing_utilization"
    assert capacity_tightness("power_generation_oem", signals) is None


# ---------------------------------------------------------------------------
# _hhi_from_counts (ontology fallback math)
# ---------------------------------------------------------------------------


def test_hhi_single_region_is_one() -> None:
    assert _hhi_from_counts({"US": 5}) == pytest.approx(1.0)


def test_hhi_equal_regions_is_one_over_n() -> None:
    assert _hhi_from_counts({"US": 1, "EU": 1, "JP": 1, "TW": 1}) == pytest.approx(0.25)


def test_hhi_floor_drops_small_regions() -> None:
    assert _hhi_from_counts({"US": 96, "TW": 4}) == pytest.approx(1.0)


def test_hhi_keeps_regions_exactly_at_floor() -> None:
    counts = {f"R{i}": 1 for i in range(20)}
    assert _hhi_from_counts(counts) == pytest.approx(1.0 / 20.0)


def test_hhi_drops_regions_below_floor() -> None:
    assert _hhi_from_counts({"US": 20, "EU": 1, "JP": 1, "TW": 1}) == pytest.approx(1.0)


def test_hhi_empty_input_returns_none() -> None:
    assert _hhi_from_counts({}) is None


def test_hhi_all_zero_returns_none() -> None:
    assert _hhi_from_counts({"US": 0, "EU": 0}) is None


# ---------------------------------------------------------------------------
# geo_concentration (ontology fallback)
# ---------------------------------------------------------------------------


class _MockWorld:
    def __init__(self, results_by_role: dict[str, list[tuple[Any, int]]]) -> None:
        self._results = results_by_role
        self.calls: list[str] = []

    def sparql(self, query: str) -> list[tuple[Any, int]]:
        self.calls.append(query)
        for role, rows in self._results.items():
            if f":{role} " in query or f":{role} ." in query:
                return list(rows)
        return []


def test_geo_concentration_with_mock_world() -> None:
    world = _MockWorld({"Foundry": [("US", 3), ("TW", 1)]})
    result = geo_concentration("advanced_node_fabs", world)
    assert result == pytest.approx(0.625)


def test_geo_concentration_none_when_world_is_none() -> None:
    assert geo_concentration("advanced_node_fabs", None) is None


def test_geo_concentration_none_for_unmapped_segment() -> None:
    world = _MockWorld({})
    assert geo_concentration("not_a_real_segment", world) is None
    assert world.calls == []


def test_geo_concentration_none_when_sparql_returns_no_rows() -> None:
    world = _MockWorld({})
    assert geo_concentration("advanced_node_fabs", world) is None


def test_geo_concentration_applies_floor_via_mock_world() -> None:
    world = _MockWorld({"IDCOperator": [("US", 96), ("TW", 4)]})
    assert geo_concentration("data_center_shell", world) == pytest.approx(1.0)


def test_geo_concentration_skips_unparseable_rows() -> None:
    world = _MockWorld({"Foundry": [("US", 3), ("TW", "not-a-number"), ("JP", 1)]})
    assert geo_concentration("advanced_node_fabs", world) == pytest.approx(0.625)
