"""Tests for app/score/extractors.py — the per-segment
capacity_tightness adapters and the ontology-driven
geo_concentration HHI.

These are pure unit tests: we pass in plain `_Row`-shaped
objects (any duck-typed objects) and assert the [0, 1] output.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

import pytest

from bottlewatch.app.score.extractors import (
    _hhi_from_counts,
    capacity_tightness,
    geo_concentration,
)


@dataclass(frozen=True)
class _Row:
    signal_name: str
    value_num: Optional[float]
    observed_at: date


def test_power_combines_forward_and_operating() -> None:
    # Forward additions = 5000 MW over 24mo (sum of planned_capacity_mw)
    # Operating capacity = 20000 MW (max of capacity_mw)
    # Ratio = 0.25 → tightness = 0.25 (modest).
    signals = [
        _Row("planned_capacity_mw", 2000.0, date(2027, 1, 1)),
        _Row("planned_capacity_mw", 3000.0, date(2027, 6, 1)),
        _Row("capacity_mw", 20000.0, date(2025, 1, 1)),
    ]
    assert capacity_tightness("power_generation_oem", signals) == pytest.approx(0.25)


def test_power_caps_at_one() -> None:
    # Forward additions exceed operating capacity → cap at 1.0.
    signals = [
        _Row("planned_capacity_mw", 30000.0, date(2027, 1, 1)),
        _Row("capacity_mw", 20000.0, date(2025, 1, 1)),
    ]
    assert capacity_tightness("power_generation_oem", signals) == pytest.approx(1.0)


def test_power_returns_none_without_capacity_signal() -> None:
    signals = [_Row("planned_capacity_mw", 100.0, date(2027, 1, 1))]
    assert capacity_tightness("power_generation_oem", signals) is None


def test_power_returns_none_without_planned_signal() -> None:
    signals = [_Row("capacity_mw", 20000.0, date(2025, 1, 1))]
    assert capacity_tightness("power_generation_oem", signals) is None


def test_data_center_shell_uses_yoy_growth() -> None:
    # 24 months of monthly sales, with a +20% YoY.
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
    # 1200 / 1000 - 1 = +0.20 → maps to (0.20 + 0.10) / 0.35 ≈ 0.857
    result = capacity_tightness("data_center_shell", signals)
    assert result == pytest.approx(0.857, abs=1e-3)


def test_data_center_shell_clamps_negative_yoy_to_zero() -> None:
    # -16.7% YoY (below the -10% floor).
    signals = []
    for m in range(1, 25):
        val = 1200.0 if m <= 12 else 1000.0
        signals.append(
            _Row(
                "retail_sales_mwh",
                val,
                date(2024, m, 1) if m <= 12 else date(2025, m - 12, 1),
            )
        )
    assert capacity_tightness("data_center_shell", signals) == 0.0


def test_data_center_shell_clamps_high_yoy_to_one() -> None:
    # +50% YoY (above the +25% ceiling).
    signals = []
    for m in range(1, 25):
        val = 1000.0 if m <= 12 else 1500.0
        signals.append(
            _Row(
                "retail_sales_mwh",
                val,
                date(2024, m, 1) if m <= 12 else date(2025, m - 12, 1),
            )
        )
    assert capacity_tightness("data_center_shell", signals) == 1.0


def test_data_center_shell_returns_none_for_short_history() -> None:
    # 12 months is not enough for a YoY delta (need 13 points).
    signals = [_Row("retail_sales_mwh", 1000.0, date(2025, m, 1)) for m in range(1, 13)]
    assert capacity_tightness("data_center_shell", signals) is None


def test_unknown_segment_returns_none() -> None:
    # transformers_tnd has no extractor in M2.
    signals = [_Row("capacity_mw", 100.0, date(2025, 1, 1))]
    assert capacity_tightness("transformers_tnd", signals) is None


def test_empty_signals_returns_none() -> None:
    assert capacity_tightness("power_generation_oem", []) is None


# ---------------------------------------------------------------------------
# _hhi_from_counts (geo_concentration math, methodology §2.3)
# ---------------------------------------------------------------------------


def test_hhi_single_region_is_one() -> None:
    # All role instances in one region → fully concentrated → HHI = 1.0.
    assert _hhi_from_counts({"US": 5}) == pytest.approx(1.0)


def test_hhi_equal_regions_is_one_over_n() -> None:
    # 4 equally-distributed regions → HHI = 1/4 = 0.25.
    assert _hhi_from_counts({"US": 1, "EU": 1, "JP": 1, "TW": 1}) == pytest.approx(0.25)


def test_hhi_floor_drops_small_regions() -> None:
    # US=96, TW=4. TW is 4% (below the 5% floor) and is dropped.
    # Renormalized: US has 100% of the qualifying total → HHI = 1.0.
    assert _hhi_from_counts({"US": 96, "TW": 4}) == pytest.approx(1.0)


def test_hhi_keeps_regions_exactly_at_floor() -> None:
    # 20 regions each with 1 instance → 1/20 = 5.0%, exactly at the
    # inclusive floor → all qualify → HHI = 1/20.
    counts = {f"R{i}": 1 for i in range(20)}
    assert _hhi_from_counts(counts) == pytest.approx(1.0 / 20.0)


def test_hhi_drops_regions_below_floor() -> None:
    # US=20, EU=JP=TW=1. Each small region is 1/23 ≈ 4.35% (dropped).
    # Renormalized: US has 100% of the qualifying total → HHI = 1.0.
    assert _hhi_from_counts({"US": 20, "EU": 1, "JP": 1, "TW": 1}) == pytest.approx(1.0)


def test_hhi_empty_input_returns_none() -> None:
    assert _hhi_from_counts({}) is None


def test_hhi_all_zero_returns_none() -> None:
    assert _hhi_from_counts({"US": 0, "EU": 0}) is None


# ---------------------------------------------------------------------------
# geo_concentration (SPARQL-driven HHI)
# ---------------------------------------------------------------------------


class _MockWorld:
    """Duck-typed stand-in for an `owlready2.World`.

    `sparql(query)` returns the rows registered for the role class
    named in the query. Tests register counts per role class and
    the mock inspects the query string to pick the right bucket.
    """

    def __init__(self, results_by_role: dict[str, list[tuple[Any, int]]]) -> None:
        self._results = results_by_role
        self.calls: list[str] = []

    def sparql(self, query: str) -> list[tuple[Any, int]]:
        self.calls.append(query)
        for role, rows in self._results.items():
            # The extractor builds queries of the form
            # `?role a :<RoleClass> .` so we match on the token.
            if f":{role} " in query or f":{role} ." in query:
                return list(rows)
        return []


def test_geo_concentration_with_mock_world() -> None:
    # Foundry instances: 3 in US, 1 in TW. total=4, no floor drop.
    # HHI = (3/4)² + (1/4)² = 9/16 + 1/16 = 10/16 = 0.625.
    world = _MockWorld({"Foundry": [("US", 3), ("TW", 1)]})
    result = geo_concentration("advanced_node_fabs", world)
    assert result == pytest.approx(0.625)


def test_geo_concentration_none_when_world_is_none() -> None:
    # Don't call extractors at all when there's no world.
    assert geo_concentration("advanced_node_fabs", None) is None


def test_geo_concentration_none_for_unmapped_segment() -> None:
    # The world should not be queried for segments with no role mapping.
    world = _MockWorld({})
    assert geo_concentration("not_a_real_segment", world) is None
    assert world.calls == []


def test_geo_concentration_none_when_sparql_returns_no_rows() -> None:
    # Role class exists in SEGMENT_TO_ROLE_CLASS but the ABox has
    # no instances of it → counts={} → None.
    world = _MockWorld({})
    assert geo_concentration("advanced_node_fabs", world) is None


def test_geo_concentration_applies_floor_via_mock_world() -> None:
    # IDCOperator: 96 in US, 4 in TW. TW is 4% (below floor) → HHI=1.0.
    world = _MockWorld({"IDCOperator": [("US", 96), ("TW", 4)]})
    assert geo_concentration("data_center_shell", world) == pytest.approx(1.0)


def test_geo_concentration_skips_unparseable_rows() -> None:
    # SPARQL may return rows where the count is a non-numeric Literal.
    # The extractor should drop the row and still compute HHI from
    # the surviving counts.
    world = _MockWorld({"Foundry": [("US", 3), ("TW", "not-a-number"), ("JP", 1)]})
    # US=3, JP=1 → total=4, no floor drop → HHI = 9/16 + 1/16 = 0.625.
    assert geo_concentration("advanced_node_fabs", world) == pytest.approx(0.625)
