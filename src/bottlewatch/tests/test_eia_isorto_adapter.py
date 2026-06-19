"""Tests for the EIA ISO/RTO (EIA-930) adapter."""

from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from bottlewatch.app.ingest import EIAISORTOAdapter, get_registry
from bottlewatch.app.ingest.eia_isorto import (
    _PAGE_SIZE,
    _coerce_value,
    _latest_capacity_month,
    _parse_daily_period,
    _region_segments,
    _states_for_regions,
)
from bottlewatch.config import Settings

_BASE_URL = "https://api.eia.gov/v2"
_REGION_PATH = "/electricity/rto/daily-region-data/data/"
_CAPACITY_PATH = "/electricity/operating-generator-capacity/data/"


def _region_envelope(data: list[dict[str, Any]]) -> dict[str, Any]:
    return {"response": {"total": len(data), "data": data}}


def _capacity_envelope(state: str, mw: float, period: str = "2026-03") -> dict[str, Any]:
    return {
        "response": {
            "total": 1,
            "data": [
                {
                    "period": period,
                    "stateid": state,
                    "nameplate-capacity-mw": str(mw),
                    "status": "OP",
                }
            ],
        }
    }


def _region_settings(settings: Settings) -> Settings:
    """Use only ERCO + CISO so capacity tests touch a small state set."""
    return settings.model_copy(update={"eia_isorto_regions": ["ERCO", "CISO"]})


def test_missing_key_is_reported_and_fetch_is_empty(settings_no_key: Settings) -> None:
    adapter = EIAISORTOAdapter(_region_settings(settings_no_key))
    ok, reason = adapter.is_configured()
    assert ok is False
    assert "EIA_API_KEY" in reason
    assert adapter.fetch(date(2024, 1, 1), date(2024, 12, 31)) == []


def test_region_and_capacity_parsing_helpers() -> None:
    assert _parse_daily_period("2025-06-14") == date(2025, 6, 14)
    assert _parse_daily_period("2025-06") is None
    assert _parse_daily_period("not-a-date") is None

    assert _coerce_value("100.5") == 100.5
    assert _coerce_value("NA") is None
    assert _coerce_value("<0.001") is None
    assert _coerce_value(None) is None

    # June 2026 → March 2026 (3-month lag for complete capacity data).
    assert _latest_capacity_month(date(2026, 6, 15)) == "2026-03"
    assert _latest_capacity_month(date(2026, 1, 5)) == "2025-10"


def test_static_mapping_utilities() -> None:
    assert _states_for_regions(("ERCO", "CISO")) == ("CA", "TX")
    assert "CA" in _states_for_regions(("CISO", "PJM"))
    assert "TX" not in _states_for_regions(("CISO", "PJM"))


def test_region_segments_respects_configured_regions(settings: Settings) -> None:
    only_ciso = settings.model_copy(update={"eia_isorto_regions": ["CISO"]})
    assert _region_segments("CISO", only_ciso) == ("power_generation_oem", "data_center_shell")
    assert _region_segments("ERCO", only_ciso) == ()


def _region_rows() -> list[dict[str, Any]]:
    """Two months of daily data for ERCO and CISO."""
    rows: list[dict[str, Any]] = []
    for region in ("ERCO", "CISO"):
        for month in (1, 2):
            for day in range(1, 6):
                rows.append(
                    {
                        "respondent": region,
                        "type": "D",
                        "period": f"2025-{month:02d}-{day:02d}",
                        "value": str(5000.0 + day * 100),
                    }
                )
                rows.append(
                    {
                        "respondent": region,
                        "type": "NG",
                        "period": f"2025-{month:02d}-{day:02d}",
                        "value": str(100000.0 + day * 1000),
                    }
                )
    return rows


def _capacity_side_effect(per_state: dict[str, float]) -> Any:
    """respx side_effect that picks the response by `facets[stateid][]`."""

    def _route(request: httpx.Request) -> httpx.Response:
        qs = parse_qs(urlparse(str(request.url)).query)
        state_values = qs.get("facets[stateid][]", [])
        state = state_values[0] if state_values else ""
        mw = per_state.get(state, 1000.0)
        return httpx.Response(200, json=_capacity_envelope(state, mw))

    return _route


def test_fetch_emits_monthly_region_signals_and_capacity(settings: Settings) -> None:
    adapter = EIAISORTOAdapter(_region_settings(settings))
    per_state = {"TX": 50000.0, "CA": 40000.0}

    with respx.mock(base_url=_BASE_URL) as mock:
        mock.get(_REGION_PATH).respond(200, json=_region_envelope(_region_rows()))
        mock.get(_CAPACITY_PATH).mock(side_effect=_capacity_side_effect(per_state))
        result = adapter.fetch(date(2025, 1, 1), date(2025, 12, 31))

    # Region signals: ERCO + CISO × 2 months × 2 signal types × 2 segments each
    # = 16, plus 2 regions × 2 segments of capacity signals = 4.
    assert len(result) == 20

    by_segment_signal: dict[tuple[str, str], list[Any]] = {}
    for sig in result:
        by_segment_signal.setdefault((sig.segment, sig.signal_name), []).append(sig)

    # Both mapped segments receive region data.
    for segment in ("power_generation_oem", "data_center_shell"):
        assert len(by_segment_signal.get((segment, "iso_peak_load_mw"), [])) == 4
        assert len(by_segment_signal.get((segment, "iso_net_generation_mwh"), [])) == 4
        assert len(by_segment_signal.get((segment, "iso_capacity_mw"), [])) == 2

    # Peak load is the largest daily value (day 5 → 5 500 MW).
    peak_signals = [s for s in result if s.signal_name == "iso_peak_load_mw"]
    assert all(s.value_num == 5500.0 for s in peak_signals)

    # Capacity signals carry the mocked state totals.
    erco_caps = [s for s in result if s.signal_name == "iso_capacity_mw" and s.geography == "ERCO"]
    assert all(s.value_num == 50000.0 for s in erco_caps)
    ciso_caps = [s for s in result if s.signal_name == "iso_capacity_mw" and s.geography == "CISO"]
    assert all(s.value_num == 40000.0 for s in ciso_caps)


def test_fetch_widens_narrow_orchestrator_window(settings: Settings) -> None:
    """Monthly-cadence runs pass a 1-month window; the adapter widens it to 2 years."""
    adapter = EIAISORTOAdapter(_region_settings(settings))
    per_state = {"TX": 50000.0, "CA": 40000.0}

    with respx.mock(base_url=_BASE_URL) as mock:
        route = mock.get(_REGION_PATH).respond(200, json=_region_envelope(_region_rows()))
        mock.get(_CAPACITY_PATH).mock(side_effect=_capacity_side_effect(per_state))
        adapter.fetch(date(2025, 6, 1), date(2025, 6, 30))

    sent = dict(route.calls.last.request.url.params.multi_items())
    assert sent.get("start") == "2023-06-30"


def test_fetch_paginates_past_page_size(settings: Settings) -> None:
    """If EIA returns a full page, the adapter follows the offset."""
    adapter = EIAISORTOAdapter(_region_settings(settings))
    per_state = {"TX": 50000.0, "CA": 40000.0}

    page1 = [{"respondent": "ERCO", "type": "D", "period": "2025-01-01", "value": "5000"}]
    page2 = [{"respondent": "CISO", "type": "D", "period": "2025-01-01", "value": "4000"}]

    def _side_effect(request: httpx.Request) -> httpx.Response:
        qs = parse_qs(urlparse(str(request.url)).query)
        offset = int(qs.get("offset", ["0"])[0])
        if offset == 0:
            return httpx.Response(200, json=_region_envelope(page1 * _PAGE_SIZE))
        return httpx.Response(200, json=_region_envelope(page2))

    with respx.mock(base_url=_BASE_URL) as mock:
        route = mock.get(_REGION_PATH).mock(side_effect=_side_effect)
        mock.get(_CAPACITY_PATH).mock(side_effect=_capacity_side_effect(per_state))
        result = adapter.fetch(date(2025, 1, 1), date(2025, 12, 31))

    assert route.call_count == 2
    assert any(s.geography == "ERCO" for s in result)
    assert any(s.geography == "CISO" for s in result)


def test_fetch_retries_on_503_then_succeeds(settings: Settings) -> None:
    adapter = EIAISORTOAdapter(_region_settings(settings))
    per_state = {"TX": 50000.0, "CA": 40000.0}

    with respx.mock(base_url=_BASE_URL) as mock:
        route = mock.get(_REGION_PATH).mock(
            side_effect=[
                httpx.Response(503, text="service unavailable"),
                httpx.Response(200, json=_region_envelope(_region_rows())),
            ]
        )
        mock.get(_CAPACITY_PATH).mock(side_effect=_capacity_side_effect(per_state))
        result = adapter.fetch(date(2025, 1, 1), date(2025, 12, 31))

    assert route.call_count == 2
    assert len(result) == 20


def test_fetch_propagates_4xx_as_hard_error(settings: Settings) -> None:
    from bottlewatch.app.ingest.eia_isorto import _EIAISORTOHardError

    adapter = EIAISORTOAdapter(_region_settings(settings))
    with respx.mock(base_url=_BASE_URL) as mock:
        mock.get(_REGION_PATH).respond(401, text="Unauthorized")
        with pytest.raises(_EIAISORTOHardError, match="401"):
            adapter.fetch(date(2025, 1, 1), date(2025, 12, 31))


def test_eia_isorto_registered_in_orchestrator() -> None:
    names = {spec.name for spec in get_registry()}
    assert "eia_isorto" in names
