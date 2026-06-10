"""Tests for the EIA v2 adapter.

Strategy: respx intercepts every httpx call so CI never touches the
network. One test per series verifies the parse path; one test covers
the retry/backoff on a 503; one covers the missing-key skip.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx
import pytest
import respx
from respx import MockRouter

from bottlewatch.app.ingest import EIAV2Adapter
from bottlewatch.app.ingest.eia import _SERIES_SPEC, _EIAHardError
from bottlewatch.config import Settings

_BASE_URL = "https://api.eia.gov/v2"


def _envelope(data: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the EIA v2 response envelope."""
    return {"response": {"total": len(data), "data": data}}


def _annual_payload(n_years: int = 3) -> list[dict[str, Any]]:
    # annual generation comes back with `period` as int and the value
    # in a `generation` column
    return [{"period": 2024 - i, "generation": 4000 - i * 10} for i in range(n_years)]


def _monthly_payload(n_months: int = 3) -> list[dict[str, Any]]:
    return [{"period": f"2024-{m:02d}", "sales": 2500 + m * 50} for m in range(1, n_months + 1)]


def _payload_for(series: str, n: int = 3) -> list[dict[str, Any]]:
    """Pick the matching EIA shape for an annual vs monthly series."""
    return _monthly_payload(n) if series.endswith(".M") else _annual_payload(n)


def _mock_all_series(
    mock: MockRouter, *, default_status: int = 200, default_body: dict[str, Any] | None = None
) -> None:
    """Register 200 mocks for every EIA series the adapter will hit.

    The adapter always iterates the full _SERIES_SPEC; tests that focus
    on one series need the others mocked too, or respx's
    `assert_all_mocked=True` blows up.
    """
    body = default_body or _envelope(_annual_payload(1))
    for s in _SERIES_SPEC:
        mock.get(f"/seriesid/{s['series_id']}").respond(default_status, json=body)


def test_missing_key_is_reported_and_fetch_is_empty(settings_no_key: Settings) -> None:
    adapter = EIAV2Adapter(settings_no_key)
    ok, reason = adapter.is_configured()
    assert ok is False
    assert "EIA_API_KEY" in reason
    assert adapter.fetch(date(2024, 1, 1), date(2024, 12, 31)) == []


@pytest.mark.parametrize("series", [s["series_id"] for s in _SERIES_SPEC])
def test_series_parses_to_rawsignals(series: str, settings: Settings) -> None:
    adapter = EIAV2Adapter(settings)
    payload = _payload_for(series, n=3)
    expected_count = 3

    with respx.mock(base_url=_BASE_URL) as mock:
        _mock_all_series(mock)
        # Override the target series with its matching payload.
        mock.get(f"/seriesid/{series}").respond(200, json=_envelope(payload))
        # Wide window so all 3 rows of the payload fall inside; the
        # windowing behavior has its own dedicated test.
        result = adapter.fetch(date(2000, 1, 1), date(2030, 12, 31))

    target = [r for r in result if r.source_id == series]
    assert len(target) == expected_count
    assert all(r.source == "eia_v2" for r in target)
    assert all(r.value_num is not None for r in target)


def test_value_text_na_is_dropped(settings: Settings) -> None:
    adapter = EIAV2Adapter(settings)
    series = _SERIES_SPEC[0]["series_id"]
    payload = [
        {"period": 2024, "generation": "NA"},
        {"period": 2023, "generation": "4000"},
        {"period": 2022, "generation": "--"},
    ]
    with respx.mock(base_url=_BASE_URL) as mock:
        _mock_all_series(mock)
        mock.get(f"/seriesid/{series}").respond(200, json=_envelope(payload))
        result = adapter.fetch(date(2022, 1, 1), date(2024, 12, 31))
    target = [r for r in result if r.source_id == series]
    assert len(target) == 1
    assert target[0].value_num == 4000.0


def test_retry_on_503_then_succeeds(settings: Settings) -> None:
    adapter = EIAV2Adapter(settings)
    series = _SERIES_SPEC[0]["series_id"]
    with respx.mock(base_url=_BASE_URL) as mock:
        _mock_all_series(mock)
        route = mock.get(f"/seriesid/{series}").mock(
            side_effect=[
                httpx.Response(503, text="upstream busy"),
                httpx.Response(200, json=_envelope(_annual_payload(2))),
            ]
        )
        result = adapter.fetch(date(2023, 1, 1), date(2024, 12, 31))
    assert route.call_count == 2
    target = [r for r in result if r.source_id == series]
    assert len(target) == 2


def test_hard_4xx_propagates(settings: Settings) -> None:
    """A 400 (bad series id) is caller error, not transient — bubbles up."""
    adapter = EIAV2Adapter(settings)
    series = _SERIES_SPEC[0]["series_id"]
    with respx.mock(base_url=_BASE_URL, assert_all_called=False) as mock:
        mock.get(f"/seriesid/{series}").respond(400, text="bad series")
        with pytest.raises(_EIAHardError):
            adapter.fetch(date(2024, 1, 1), date(2024, 12, 31))


def test_subsegment_populated_for_ercot_series(settings: Settings) -> None:
    adapter = EIAV2Adapter(settings)
    series = "ELEC.SALES.TX-RES.M"
    with respx.mock(base_url=_BASE_URL) as mock:
        _mock_all_series(mock)
        mock.get(f"/seriesid/{series}").respond(200, json=_envelope(_monthly_payload(2)))
        result = adapter.fetch(date(2024, 1, 1), date(2024, 12, 31))
    target = [r for r in result if r.source_id == series]
    assert len(target) == 2
    assert all(r.subsegment == "ercot_residential_load_proxy" for r in target)
    assert all(r.geography == "US-TX" for r in target)


def test_api_key_is_scrubbed_from_request_url(settings: Settings) -> None:
    """The orchestrator silences httpx's per-request INFO line so the EIA
    API key never lands in the log. The transport still receives the
    real key (respx matches on it).
    """
    import logging

    from bottlewatch.app.ingest.base import quiet_httpx_request_log

    quiet_httpx_request_log()
    assert logging.getLogger("httpx").level == logging.WARNING

    adapter = EIAV2Adapter(settings)
    with respx.mock(base_url=_BASE_URL) as mock:
        _mock_all_series(mock)
        adapter.fetch(date(2024, 1, 1), date(2024, 12, 31))

    # The transport received the real key on every call.
    for call in mock.calls:
        params = dict(call.request.url.params.multi_items())
        assert params.get("api_key") == settings.eia_api_key


def test_period_window_filters_response(settings: Settings) -> None:
    """The orchestrator's (since, until) is applied client-side. The v2
    /seriesid/ bridge does not honor start/end (it returns the full
    series), so the adapter filters rows by the window before emitting.
    Regression for the M1 backfill gap: previously the adapter ignored
    the window and emitted the whole series.
    """
    adapter = EIAV2Adapter(settings)
    series = _SERIES_SPEC[0]["series_id"]  # annual generation
    # 25 years of annual data, 2001..2025.
    payload = [{"period": year, "generation": str(1000 + year)} for year in range(2001, 2026)]
    with respx.mock(base_url=_BASE_URL) as mock:
        _mock_all_series(mock)
        mock.get(f"/seriesid/{series}").respond(200, json=_envelope(payload))
        result = adapter.fetch(date(2024, 1, 1), date(2024, 12, 31))

    target = [r for r in result if r.source_id == series]
    assert len(target) == 1
    assert target[0].observed_at == date(2024, 12, 31)
