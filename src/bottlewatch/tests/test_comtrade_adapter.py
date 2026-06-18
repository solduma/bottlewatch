"""Tests for the Comtrade adapter."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import httpx
import respx

from bottlewatch.app.ingest import ComtradeAdapter
from bottlewatch.config import Settings


def _envelope(data: list[dict[str, Any]]) -> dict[str, Any]:
    return {"data": data}


def test_missing_key_is_reported_and_fetch_is_empty(settings_no_key: Settings) -> None:
    adapter = ComtradeAdapter(settings_no_key)
    ok, reason = adapter.is_configured()
    assert ok is False
    assert "COMTRADE_API_KEY" in reason
    assert adapter.fetch(date(2024, 1, 1), date(2024, 12, 31)) == []


def test_commodity_parses_to_rawsignals(settings: Settings) -> None:
    adapter = ComtradeAdapter(settings)
    payload = [
        {"period": "2024-01", "tradeValue": "1000000.0"},
        {"period": "2024-02", "tradeValue": "1100000.0"},
        {"period": "2024-03", "tradeValue": "."},  # Missing
        {"period": "2024-04", "tradeValue": "1200000.0"},
    ]

    with respx.mock(base_url="https://comtradeapi.un.org") as mock:
        mock.get("/api/get").respond(200, json=_envelope(payload))
        result = adapter.fetch(date(2024, 1, 1), date(2024, 12, 31))

    # 4 commodities in spec, 3 valid observations each = 12 signals
    from bottlewatch.app.ingest.comtrade import _COMMODITY_SPEC

    expected_count = 3 * len(_COMMODITY_SPEC)
    assert len(result) == expected_count
    assert result[0].value_num == 1000000.0
    assert result[0].source == "comtrade"
    assert result[0].geography == "US"
    # HS codes map to canonical scoring segment slugs.
    segments = {s.segment for s in result}
    assert segments == {"hbm_memory", "advanced_packaging", "transformers_tnd"}


def test_retry_on_503_then_succeeds(settings: Settings) -> None:
    adapter = ComtradeAdapter(settings)
    payload = [{"period": "2024-01", "tradeValue": "100.0"}]

    with respx.mock(base_url="https://comtradeapi.un.org") as mock:
        route = mock.get("/api/get").mock(
            side_effect=[
                httpx.Response(503, text="service unavailable"),
                httpx.Response(200, json=_envelope(payload)),
            ]
        )
        result = adapter.fetch(date(2024, 1, 1), date(2024, 12, 31))

    assert route.call_count == 2
    assert len(result) > 0


def test_failing_commodity_is_logged_and_skipped(settings: Settings, caplog) -> None:
    # A commodity that 404s on every attempt must be logged-and-skipped,
    # not silently swallowed — otherwise a degraded fetch reads as a clean
    # empty run.
    adapter = ComtradeAdapter(settings)
    with respx.mock(base_url="https://comtradeapi.un.org") as mock:
        mock.get("/api/get").respond(404, text="not found")
        with caplog.at_level(logging.WARNING):
            result = adapter.fetch(date(2024, 1, 1), date(2024, 12, 31))
    assert result == []
    assert any("Comtrade HS code" in r.message and "failed" in r.message for r in caplog.records)
