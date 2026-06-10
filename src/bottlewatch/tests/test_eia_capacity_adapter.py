"""Tests for the EIA v2 capacity aggregator.

The adapter fetches per-generator rows for each of 51 states (50 + DC)
and emits one signal per state plus a US total. We mock the network
per-state to control the totals; tests don't touch the real EIA.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from bottlewatch.app.ingest import EIAV2CapacityAdapter
from bottlewatch.app.ingest.eia_capacity import _STATES, _latest_month_window
from bottlewatch.config import Settings

_BASE_URL = "https://api.eia.gov/v2"
_CAPACITY_PATH = "/electricity/operating-generator-capacity/data/"


def _envelope(data: list[dict[str, Any]]) -> dict[str, Any]:
    return {"response": {"total": len(data), "data": data}}


def _gen_row(state: str, mw: float, period: str = "2026-04") -> dict[str, Any]:
    return {
        "period": period,
        "stateid": state,
        "stateName": _state_name(state),
        "sector": "ipp-non-chp",
        "sectorName": "IPP Non-CHP",
        "entityid": "1",
        "entityName": "Acme Power",
        "plantid": "1",
        "plantName": "Acme Plant",
        "generatorid": "1",
        "technology": "Natural Gas Fired Combustion Turbine",
        "energy_source_code": "NG",
        "prime_mover_code": "GT",
        "status": "OP",
        "nameplate-capacity-mw": str(mw),
        "nameplate-capacity-mw-units": "MW",
    }


def _state_name(state: str) -> str:
    return {"TX": "Texas", "CA": "California"}.get(state, state)


def _per_state_side_effect(
    *,
    per_state: dict[str, list[float]],
    hard_error_states: set[str] = set(),
) -> Any:
    """Return a `respx` side_effect that picks the response by stateid.

    The capacity adapter's per-state call shares the same URL path
    across all 51 states; only the `facets[stateid][]` query param
    differs. respx matches on path by default, so we have to inspect
    the request URL to know which state is being asked for.

    `per_state` maps state -> list of generator MW values. We turn
    each MW into a fake EIA v2 row on the way out.
    """

    def _route(request: httpx.Request) -> httpx.Response:
        qs = parse_qs(urlparse(str(request.url)).query)
        state_values = qs.get("facets[stateid][]", [])
        state = state_values[0] if state_values else ""
        if state in hard_error_states:
            return httpx.Response(400, text="bad state")
        # An entry in `per_state` with an empty list means "this state
        # has no rows"; an absent entry means "not part of this test"
        # (use a sentinel default so the caller can distinguish).
        mws = per_state[state] if state in per_state else [100.0]
        rows = [_gen_row(state, mw) for mw in mws]
        return httpx.Response(200, json=_envelope(rows))

    return _route


def test_missing_key_is_skipped(settings_no_key: Settings) -> None:
    adapter = EIAV2CapacityAdapter(settings_no_key)
    ok, reason = adapter.is_configured()
    assert ok is False
    assert "EIA_API_KEY" in reason
    assert adapter.fetch(date(2024, 1, 1), date(2024, 12, 31)) == []


def test_latest_month_window_walks_back_three_months() -> None:
    # June → March (Apr/May may be partial; March is reliably complete).
    assert _latest_month_window(date(2026, 6, 3)) == ("2026-03", "2026-03")
    # January → October of the prior year.
    assert _latest_month_window(date(2026, 1, 15)) == ("2025-10", "2025-10")
    # March → December of the prior year.
    assert _latest_month_window(date(2026, 3, 1)) == ("2025-12", "2025-12")


def test_happy_path_emits_one_signal_per_state_plus_us_total(settings: Settings) -> None:
    adapter = EIAV2CapacityAdapter(settings)
    per_state = {state: [100.0, 200.0] for state in _STATES}
    with respx.mock(base_url=_BASE_URL) as mock:
        mock.get(_CAPACITY_PATH).mock(side_effect=_per_state_side_effect(per_state=per_state))
        result = adapter.fetch(date(2024, 1, 1), date(2024, 12, 31))

    # 51 state rows + 1 US total = 52.
    assert len(result) == len(_STATES) + 1
    state_signals = [r for r in result if r.geography != "US"]
    us_signals = [r for r in result if r.geography == "US"]
    assert len(state_signals) == len(_STATES)
    assert len(us_signals) == 1
    # Each state's two generators sum to 300 MW.
    assert all(r.value_num == 300.0 for r in state_signals)
    # The US total is the sum of state totals: 51 * 300 = 15,300 MW.
    assert us_signals[0].value_num == 300.0 * len(_STATES)
    for r in result:
        assert r.unit == "MW"
        assert r.segment == "power_generation_oem"
        assert r.signal_name == "capacity_mw"
        assert r.source == "eia_v2_capacity"


def test_empty_state_is_zero_not_error(settings: Settings) -> None:
    """A state with no rows (e.g. DC if it returns empty) emits 0.0, not ERROR."""
    adapter = EIAV2CapacityAdapter(settings)
    per_state = {state: [50.0] for state in _STATES if state != "DC"}
    per_state["DC"] = []  # explicit empty: the side_effect turns this into 0.0
    with respx.mock(base_url=_BASE_URL) as mock:
        mock.get(_CAPACITY_PATH).mock(side_effect=_per_state_side_effect(per_state=per_state))
        result = adapter.fetch(date(2024, 1, 1), date(2024, 12, 31))

    dc = [r for r in result if r.geography == "US-DC"]
    assert len(dc) == 1
    assert dc[0].value_num == 0.0


def test_hard_4xx_on_some_states_keeps_others_running(settings: Settings) -> None:
    """A 400 on some states is logged and skipped, but the surviving
    states still emit a US total. The orchestrator marks the run OK
    if at least one state succeeded.
    """
    adapter = EIAV2CapacityAdapter(settings)
    per_state = {state: [100.0] for state in _STATES}
    hard_errors = {"TX", "CA", "FL"}
    with respx.mock(base_url=_BASE_URL) as mock:
        mock.get(_CAPACITY_PATH).mock(
            side_effect=_per_state_side_effect(per_state=per_state, hard_error_states=hard_errors)
        )
        result = adapter.fetch(date(2024, 1, 1), date(2024, 12, 31))

    # 48 surviving states + 1 US total.
    surviving = [r for r in result if r.geography != "US"]
    us = [r for r in result if r.geography == "US"]
    assert len(surviving) == len(_STATES) - 3
    assert us[0].value_num == 100.0 * (len(_STATES) - 3)


def test_all_states_hard_error_propagates(settings: Settings) -> None:
    """If every state 4xx's, the adapter raises so the orchestrator records ERROR."""
    from bottlewatch.app.ingest.eia_capacity import _EIAHardError

    adapter = EIAV2CapacityAdapter(settings)
    with respx.mock(base_url=_BASE_URL) as mock:
        mock.get(_CAPACITY_PATH).mock(side_effect=_per_state_side_effect(per_state={}, hard_error_states=set(_STATES)))
        with pytest.raises(_EIAHardError):
            adapter.fetch(date(2024, 1, 1), date(2024, 12, 31))


def test_httpx_request_logger_is_quieted(settings: Settings) -> None:
    """The orchestrator silences httpx's per-request INFO line so the EIA
    API key never lands in the log. The transport still receives the
    real key (respx matches on it).
    """
    import logging

    from bottlewatch.app.ingest.base import quiet_httpx_request_log

    quiet_httpx_request_log()
    assert logging.getLogger("httpx").level == logging.WARNING

    # Sanity: a real fetch still sends api_key=... (not "***") to the transport.
    adapter = EIAV2CapacityAdapter(settings)
    with respx.mock(base_url=_BASE_URL) as mock:
        route = mock.get(_CAPACITY_PATH).mock(side_effect=_per_state_side_effect(per_state={"TX": [50.0]}))
        adapter.fetch(date(2024, 1, 1), date(2024, 12, 31))

    sent_params = dict(route.calls.last.request.url.params.multi_items())
    assert sent_params.get("api_key") == settings.eia_api_key
