"""Tests for the FRED adapter."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import httpx
import respx

from bottlewatch.app.ingest import FredAdapter, get_registry
from bottlewatch.app.ingest.fred import _SERIES_SPEC
from bottlewatch.config import Settings


def _envelope(data: list[dict[str, Any]]) -> dict[str, Any]:
    return {"observations": data}


def test_missing_key_is_reported_and_fetch_is_empty(settings_no_key: Settings) -> None:
    adapter = FredAdapter(settings_no_key)
    ok, reason = adapter.is_configured()
    assert ok is False
    assert "FRED_API_KEY" in reason
    assert adapter.fetch(date(2024, 1, 1), date(2024, 12, 31)) == []


def test_series_parses_to_rawsignals(settings: Settings) -> None:
    adapter = FredAdapter(settings)
    payload = [
        {"date": "2024-01-01", "value": "100.5"},
        {"date": "2024-01-08", "value": "101.2"},
        {"date": "2024-01-15", "value": "."},  # Missing value
        {"date": "2024-01-22", "value": "102.1"},
    ]

    with respx.mock(base_url="https://api.stlouisfed.org") as mock:
        mock.get("/fred/series/observations").respond(200, json=_envelope(payload))
        result = adapter.fetch(date(2024, 1, 1), date(2024, 12, 31))

    # Should have 3 signals per target segment for each series.
    expected_count = 3 * sum(len(s.segments) for s in _SERIES_SPEC)
    assert len(result) == expected_count
    assert result[0].value_num == 100.5
    assert result[0].observed_at == date(2024, 1, 1)
    assert result[0].source == "fred"


def test_retry_on_503_then_succeeds(settings: Settings) -> None:
    adapter = FredAdapter(settings)
    payload = [{"date": "2024-01-01", "value": "100.0"}]

    with respx.mock(base_url="https://api.stlouisfed.org") as mock:
        route = mock.get("/fred/series/observations").mock(
            side_effect=[
                httpx.Response(503, text="service unavailable"),
                httpx.Response(200, json=_envelope(payload)),
            ]
        )
        result = adapter.fetch(date(2024, 1, 1), date(2024, 12, 31))

    assert route.call_count == 2
    # One series * its number of target segments.
    assert len(result) == len(_SERIES_SPEC[0].segments)
    assert result[0].value_num == 100.0


def test_failing_series_is_logged_and_skipped(settings: Settings, caplog) -> None:
    # A series that 404s on every attempt must not silently vanish: the
    # adapter logs a WARNING and continues, so a degraded fetch is visible
    # rather than reported as a clean empty run.
    adapter = FredAdapter(settings)
    with respx.mock(base_url="https://api.stlouisfed.org") as mock:
        mock.get("/fred/series/observations").respond(404, text="not found")
        with caplog.at_level(logging.WARNING):
            result = adapter.fetch(date(2024, 1, 1), date(2024, 12, 31))
    assert result == []
    assert any("FRED series" in r.message and "failed" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Wiring: FRED must be registered in the orchestrator's adapter registry
# and its _SERIES_SPEC must match research/03_data_sources.md §4.
# ---------------------------------------------------------------------------


def test_fred_registered_in_orchestrator() -> None:
    # The refresh_daily orchestrator iterates get_registry() to dispatch
    # each adapter. If FRED is missing here, no FRED signals are ever
    # fetched — and `transformers_tnd` will be stuck on a None
    # capacity_tightness forever.
    names = {spec.name for spec in get_registry()}
    assert "fred" in names


def test_series_spec_matches_research() -> None:
    # Locked in: 5 series, with the segment/signal mapping from
    # research/03_data_sources.md §4. A typo here would silently 404
    # against the real FRED API.
    as_tuples = {(s.series_id, tuple(s.segments), s.signal_name) for s in _SERIES_SPEC}
    assert (
        "INDPRO",
        ("systems_rack_scale", "cooling_water", "power_generation_oem"),
        "industrial_production",
    ) in as_tuples
    assert ("TCU", ("systems_rack_scale", "cooling_water", "power_generation_oem"), "capacity_utilization") in as_tuples
    assert (
        "WPU31132506",
        ("advanced_node_fabs", "hbm_memory", "gpu_asic_silicon", "networking_interconnect", "advanced_packaging"),
        "ppi_semis",
    ) in as_tuples
    assert ("WPU1321", ("transformers_tnd",), "ppi_transformers") in as_tuples
    # A35SNO = manufacturers' new orders for electrical equipment,
    # appliances, and components. The upstream demand-pull proxy
    # for the `transformers_tnd` segment (per methodology §2.5 —
    # FRED doesn't aggregate hyperscaler capex; this is the
    # closest direct proxy). Added 2026-06-10 to make the
    # transformers_tnd segment's `demand_signal` sub-score
    # dynamic instead of hand-curated from scoring_seed.json.
    assert ("A35SNO", ("transformers_tnd",), "electrical_equipment_orders") in as_tuples
    assert len(_SERIES_SPEC) == 5
