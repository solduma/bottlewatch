"""Tests for the EIA Electric adapter.

The adapter now does a real HTTP call to the EIA v2
`electricity/retail-sales` route. We mock with respx so CI
runs offline; the route is parameterized to read from
`settings.eia_base_url`, so we mock that base URL.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx
import pytest
import respx

from bottlewatch.app.ingest import EIAElectricAdapter
from bottlewatch.app.ingest.eia_electric import (
    _EIAElectricHardError,
    _coerce_value,
    _parse_period,
)
from bottlewatch.config import Settings


def _envelope(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"response": {"total": len(rows), "data": rows}}


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_coerce_value_drops_na_and_empty() -> None:
    assert _coerce_value(None) is None
    assert _coerce_value("") is None
    assert _coerce_value("NA") is None
    assert _coerce_value("--") is None
    assert _coerce_value("not-a-number") is None
    assert _coerce_value("100.5") == 100.5
    assert _coerce_value(42.0) == 42.0
    # EIA emits "<0.001" for very small values; we drop those (the
    # value is below our precision floor).
    assert _coerce_value("<0.001") is None


def test_parse_period_monthly_formats() -> None:
    assert _parse_period("2025-03") == date(2025, 3, 1)
    assert _parse_period("2024-12") == date(2024, 12, 1)
    assert _parse_period("2025-13") is None  # bad month
    assert _parse_period("") is None
    assert _parse_period("not-a-period") is None
    # Annual periods (YYYY) are not supported by the retail-sales route.
    assert _parse_period("2025") is None


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_eia_electric_is_configured(settings: Settings) -> None:
    adapter = EIAElectricAdapter(settings)
    ok, reason = adapter.is_configured()
    assert ok is True
    assert reason == ""


def test_eia_electric_not_configured_when_key_missing(settings_no_key: Settings) -> None:
    adapter = EIAElectricAdapter(settings_no_key)
    ok, reason = adapter.is_configured()
    assert ok is False
    assert "EIA_API_KEY" in reason
    assert adapter.fetch(date(2024, 1, 1), date(2024, 12, 31)) == []


# ---------------------------------------------------------------------------
# fetch() — real shape, mocked HTTP
# ---------------------------------------------------------------------------


def _sample_rows() -> list[dict[str, Any]]:
    """24 months of national industrial retail sales, ending 2025-12."""
    rows = []
    for year in (2024, 2025):
        for month in range(1, 13):
            rows.append(
                {
                    "period": f"{year}-{month:02d}",
                    "stateid": "US",
                    "stateDescription": "United States",
                    "sectorid": "IND",
                    "sectorName": "industrial",
                    "sales": f"{25000 + (year - 2024) * 500 + month * 10:.3f}",
                    "sales-units": "million kilowatt hours",
                }
            )
    return rows


def test_fetch_returns_24_signals_with_correct_shape(settings: Settings) -> None:
    adapter = EIAElectricAdapter(settings)
    with respx.mock(base_url=settings.eia_base_url) as mock:
        mock.get("/seriesid/ELEC.SALES.US-IND.M").respond(200, json=_envelope(_sample_rows()))
        result = adapter.fetch(date(2024, 1, 1), date(2025, 12, 31))

    assert len(result) == 24
    for sig in result:
        assert sig.segment == "data_center_shell"
        assert sig.signal_name == "retail_sales_industrial"
        assert sig.unit == "million_kWh"
        assert sig.geography == "US-IND"
        assert sig.source == "eia_electric"
        assert sig.value_num is not None
        assert sig.value_num > 0


def test_fetch_filters_by_window(settings: Settings) -> None:
    """Signals outside [period_start, period_end] are dropped.

    Uses a wide window (>= 2 years) so the adapter's internal
    "widen the orchestrator's narrow monthly window" override
    doesn't kick in — that override is for production only.
    """
    adapter = EIAElectricAdapter(settings)
    with respx.mock(base_url=settings.eia_base_url) as mock:
        mock.get("/seriesid/ELEC.SALES.US-IND.M").respond(200, json=_envelope(_sample_rows()))
        result = adapter.fetch(date(2023, 1, 1), date(2025, 12, 31))

    # The fixture covers 2024-2025 (24 rows); both endpoints inside the window.
    assert len(result) == 24
    periods = [r.observed_at for r in result]
    assert all(date(2023, 1, 1) <= p <= date(2025, 12, 1) for p in periods)


def test_fetch_observed_at_is_first_of_month(settings: Settings) -> None:
    adapter = EIAElectricAdapter(settings)
    with respx.mock(base_url=settings.eia_base_url) as mock:
        mock.get("/seriesid/ELEC.SALES.US-IND.M").respond(200, json=_envelope(_sample_rows()))
        # Wide window so the production override doesn't widen it
        # further.
        result = adapter.fetch(date(2023, 1, 1), date(2025, 12, 31))

    # All 24 fixture months land on the 1st of the month.
    for sig in result:
        assert sig.observed_at.day == 1


def test_fetch_drops_non_numeric_sales(settings: Settings) -> None:
    """EIA emits "NA" / "" / "<0.001" for missing values; we drop them."""
    rows = _sample_rows()
    rows[5]["sales"] = "NA"  # 2024-06
    rows[10]["sales"] = ""  # 2024-11
    rows[15]["sales"] = "<0.001"  # 2025-04
    adapter = EIAElectricAdapter(settings)
    with respx.mock(base_url=settings.eia_base_url) as mock:
        mock.get("/seriesid/ELEC.SALES.US-IND.M").respond(200, json=_envelope(rows))
        result = adapter.fetch(date(2024, 1, 1), date(2025, 12, 31))

    # 24 total - 3 dropped = 21 signals
    assert len(result) == 21
    periods = [r.observed_at for r in result]
    assert date(2024, 6, 1) not in periods
    assert date(2024, 11, 1) not in periods
    assert date(2025, 4, 1) not in periods


def test_fetch_handles_empty_response(settings: Settings) -> None:
    """EIA sometimes returns 0 rows for a window — we should not crash."""
    adapter = EIAElectricAdapter(settings)
    with respx.mock(base_url=settings.eia_base_url) as mock:
        mock.get("/seriesid/ELEC.SALES.US-IND.M").respond(200, json=_envelope([]))
        result = adapter.fetch(date(2024, 1, 1), date(2024, 12, 31))
    assert result == []


def test_fetch_propagates_4xx_as_hard_error(settings: Settings) -> None:
    """A bad key or invalid facets → hard error, not silent 0 rows."""
    adapter = EIAElectricAdapter(settings)
    with respx.mock(base_url=settings.eia_base_url) as mock:
        mock.get("/seriesid/ELEC.SALES.US-IND.M").respond(401, text="Unauthorized")
        with pytest.raises(_EIAElectricHardError, match="401"):
            adapter.fetch(date(2024, 1, 1), date(2024, 12, 31))


def test_fetch_retries_on_503_then_succeeds(settings: Settings) -> None:
    """5xx → retry; second call succeeds."""
    adapter = EIAElectricAdapter(settings)
    with respx.mock(base_url=settings.eia_base_url) as mock:
        route = mock.get("/seriesid/ELEC.SALES.US-IND.M").mock(
            side_effect=[
                httpx.Response(503, text="Service Unavailable"),
                httpx.Response(200, json=_envelope(_sample_rows())),
            ]
        )
        result = adapter.fetch(date(2024, 1, 1), date(2024, 12, 31))
    assert route.call_count == 2
    assert len(result) == 12  # 12 months in 2024
