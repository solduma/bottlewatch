"""Tests for the EIA-860M planned-additions adapter.

The adapter downloads the latest monthly 860M XLSX from eia.gov,
parses the `Planned` tab, and emits one signal per planned generator.
No API key; the file is public. We mock the HTTP download with respx
and use a fixture XLSX built via polars for the parse path so tests
don't depend on the 13MB real file.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import cast

import polars as pl
import pytest
import respx

from bottlewatch.app.ingest.eia_860m import (
    EIA860MAdapter,
    _EIA860MHardError,
    _cache_path,
    _latest_release_month,
    _url_for,
)
from bottlewatch.config import Settings

_DOWNLOAD_URL = "https://www.eia.gov/electricity/data/eia860m/xls/april_generator2026.xlsx"


def _build_fixture_xlsx(path: Path, rows: list[dict[str, object]]) -> None:
    """Write a minimal XLSX that mimics the real 860M Planned tab:
    row 1 = title, row 2 = blank, row 3 = header, rows 4..N = data.
    polars serializes None as empty string, which matches what the
    parser expects to handle.
    """
    cols = [
        "Entity ID",
        "Entity Name",
        "Plant ID",
        "Plant Name",
        "Google Map",
        "Bing Map",
        "Plant State",
        "County",
        "Balancing Authority Code",
        "Sector",
        "Generator ID",
        "Unit Code",
        "Nameplate Capacity (MW)",
        "Net Summer Capacity (MW)",
        "Net Winter Capacity (MW)",
        "Technology",
        "Energy Source Code",
        "Prime Mover Code",
        "Planned Operation Month",
        "Planned Operation Year",
        "Status",
        "Latitude",
        "Longitude",
    ]
    # Row 1: title (first cell non-null so fastexcel doesn't drop it).
    # Row 2: all blank (kept by the parser via drop_empty_rows=False).
    # Row 3: header.
    # Row 4..: data.
    title_row: list[object] = cast(
        list[object], ["Inventory of Planned Generators as of April 2026"] + [None] * (len(cols) - 1)
    )
    blank_row: list[object] = [None] * len(cols)
    header_row: list[object] = list(cols)
    body: list[list[object]] = [title_row, blank_row, header_row]
    body.extend([list(r.get(c) for c in cols) for r in rows])
    full = pl.DataFrame(body, schema=cols, orient="row")
    full.write_excel(path, worksheet="Planned", include_header=False)


def test_is_configured_is_always_true(settings: Settings) -> None:
    adapter = EIA860MAdapter(settings)
    ok, reason = adapter.is_configured()
    assert ok is True
    assert reason == ""


def test_latest_release_month_walks_back_two_months() -> None:
    # June → April
    assert _latest_release_month(date(2026, 6, 3)) == (2026, 4)
    # January → November of the prior year
    assert _latest_release_month(date(2026, 1, 15)) == (2025, 11)
    # March → January
    assert _latest_release_month(date(2026, 3, 1)) == (2026, 1)


def test_url_for_uses_archive_path() -> None:
    assert _url_for(2026, 4) == _DOWNLOAD_URL


def test_cache_path_is_under_settings_cache_dir(settings: Settings) -> None:
    path = _cache_path(settings, 2026, 4)
    assert path.name == "april_generator2026.xlsx"
    assert path.parent == settings.refresh_log_path.parent / "eia860m"


def test_fetch_emits_one_signal_per_planned_row(settings: Settings, tmp_path: Path) -> None:
    """A fixture XLSX with 3 planned rows → 3 RawSignals with the
    expected segment / signal_name / unit / value / geography.
    """
    xlsx = tmp_path / "fixture.xlsx"
    _build_fixture_xlsx(
        xlsx,
        rows=[
            {
                "Entity ID": "1",
                "Plant ID": "1",
                "Generator ID": "1",
                "Plant State": "TX",
                "Nameplate Capacity (MW)": "100.5",
                "Prime Mover Code": "GT",
                "Energy Source Code": "NG",
                "Planned Operation Month": "7",
                "Planned Operation Year": "2027",
                "Status": "(V) Under construction, more than 50 percent complete",
            },
            {
                "Entity ID": "2",
                "Plant ID": "2",
                "Generator ID": "1",
                "Plant State": "CA",
                "Nameplate Capacity (MW)": "20",
                "Prime Mover Code": "BA",
                "Energy Source Code": "MWH",
                "Planned Operation Month": "12",
                "Planned Operation Year": "2026",
                "Status": "(TS) Construction complete, but not yet in commercial operation",
            },
            {
                "Entity ID": "3",
                "Plant ID": "3",
                "Generator ID": "1",
                "Plant State": "NY",
                "Nameplate Capacity (MW)": "5",
                "Prime Mover Code": "PV",
                "Energy Source Code": "SUN",
                "Planned Operation Month": "",
                "Planned Operation Year": "2028",
                "Status": "(U) Under construction, less than or equal to 50 percent complete",
            },
        ],
    )

    with respx.mock() as mock:
        route = mock.get(_DOWNLOAD_URL).respond(200, content=xlsx.read_bytes())
        # Override settings so the cache lives in tmp_path
        settings_with_cache = settings.model_copy(update={"refresh_log_path": tmp_path / "refresh.log"})
        adapter2 = EIA860MAdapter(settings_with_cache)
        result = adapter2.fetch(date(2024, 1, 1), date(2024, 12, 31))

    assert route.call_count == 1
    assert len(result) == 3
    assert all(s.segment == "power_generation_oem" for s in result)
    assert all(s.signal_name == "planned_capacity_mw" for s in result)
    assert all(s.unit == "MW" for s in result)
    assert all(s.source == "eia_860m" for s in result)
    by_state = {s.geography: s for s in result}
    assert by_state["US-TX"].value_num == 100.5
    assert by_state["US-TX"].observed_at == date(2027, 7, 1)
    assert by_state["US-CA"].value_num == 20.0
    assert by_state["US-CA"].observed_at == date(2026, 12, 1)
    # Blank month → fall back to release month (April).
    assert by_state["US-NY"].observed_at == date(2028, 4, 1)
    # subsegment encodes the prime mover + fuel so the scoring engine
    # can group by tech.
    assert by_state["US-TX"].subsegment == "planned:GT:NG"
    assert by_state["US-CA"].subsegment == "planned:BA:MWH"
    # value_text captures the EIA status label verbatim.
    assert "(V) Under construction" in (by_state["US-TX"].value_text or "")


def test_row_missing_year_is_dropped(settings: Settings, tmp_path: Path) -> None:
    """Rows without a Planned Operation Year are dropped (e.g. status='T'
    regulatory approvals with no committed year yet)."""
    xlsx = tmp_path / "fixture.xlsx"
    _build_fixture_xlsx(
        xlsx,
        rows=[
            {
                "Entity ID": "1",
                "Plant ID": "1",
                "Generator ID": "1",
                "Plant State": "TX",
                "Nameplate Capacity (MW)": "100",
                "Prime Mover Code": "GT",
                "Energy Source Code": "NG",
                "Planned Operation Month": "1",
                "Planned Operation Year": "2027",  # present
                "Status": "(U)",
            },
            {
                "Entity ID": "2",
                "Plant ID": "2",
                "Generator ID": "1",
                "Plant State": "CA",
                "Nameplate Capacity (MW)": "50",
                "Prime Mover Code": "PV",
                "Energy Source Code": "SUN",
                "Planned Operation Month": "",
                "Planned Operation Year": "",  # missing → drop
                "Status": "(T) Regulatory approvals received. Not under construction",
            },
        ],
    )
    adapter = EIA860MAdapter(settings.model_copy(update={"refresh_log_path": tmp_path / "refresh.log"}))
    with respx.mock() as mock:
        mock.get(_DOWNLOAD_URL).respond(200, content=xlsx.read_bytes())
        result = adapter.fetch(date(2024, 1, 1), date(2024, 12, 31))
    assert len(result) == 1
    assert result[0].geography == "US-TX"


def test_cache_hit_skips_second_download(settings: Settings, tmp_path: Path) -> None:
    """A second fetch within the same release month must NOT hit the
    network. The download is ~13MB and EIA has no rate limit, but the
    point is to keep refresh idempotent.
    """
    xlsx = tmp_path / "fixture.xlsx"
    _build_fixture_xlsx(
        xlsx,
        rows=[
            {
                "Entity ID": "1",
                "Plant ID": "1",
                "Generator ID": "1",
                "Plant State": "TX",
                "Nameplate Capacity (MW)": "100",
                "Prime Mover Code": "GT",
                "Energy Source Code": "NG",
                "Planned Operation Month": "1",
                "Planned Operation Year": "2027",
                "Status": "(V)",
            }
        ],
    )
    adapter = EIA860MAdapter(settings.model_copy(update={"refresh_log_path": tmp_path / "refresh.log"}))
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(_DOWNLOAD_URL).respond(200, content=xlsx.read_bytes())
        adapter.fetch(date(2024, 1, 1), date(2024, 12, 31))
        adapter.fetch(date(2024, 1, 1), date(2024, 12, 31))
    assert route.call_count == 1


def test_4xx_download_raises(settings: Settings, tmp_path: Path) -> None:
    adapter = EIA860MAdapter(settings.model_copy(update={"refresh_log_path": tmp_path / "refresh.log"}))
    with respx.mock() as mock:
        mock.get(_DOWNLOAD_URL).respond(404, text="not found")
        with pytest.raises(_EIA860MHardError):
            adapter.fetch(date(2024, 1, 1), date(2024, 12, 31))


def test_download_follows_redirects(settings: Settings, tmp_path: Path) -> None:
    """EIA occasionally serves the file from a redirected URL; the
    client must follow the redirect to land on the actual XLSX.
    """
    xlsx = tmp_path / "fixture.xlsx"
    _build_fixture_xlsx(
        xlsx,
        rows=[
            {
                "Entity ID": "1",
                "Plant ID": "1",
                "Generator ID": "1",
                "Plant State": "TX",
                "Nameplate Capacity (MW)": "100",
                "Prime Mover Code": "GT",
                "Energy Source Code": "NG",
                "Planned Operation Month": "1",
                "Planned Operation Year": "2027",
                "Status": "(V)",
            }
        ],
    )
    adapter = EIA860MAdapter(settings.model_copy(update={"refresh_log_path": tmp_path / "refresh.log"}))
    with respx.mock() as mock:
        mock.get(_DOWNLOAD_URL).respond(302, headers={"location": "https://cdn.eia.gov/x"})
        mock.get("https://cdn.eia.gov/x").respond(200, content=xlsx.read_bytes())
        result = adapter.fetch(date(2024, 1, 1), date(2024, 12, 31))
    assert len(result) == 1
    assert result[0].geography == "US-TX"


def test_empty_planned_tab_raises(settings: Settings, tmp_path: Path) -> None:
    """An XLSX with no Planned rows (header only) must hard-error so the
    orchestrator records ERROR — silently returning 0 signals would mask
    a broken parser or a wrong file format version."""
    xlsx = tmp_path / "fixture.xlsx"
    _build_fixture_xlsx(xlsx, rows=[])
    adapter = EIA860MAdapter(settings.model_copy(update={"refresh_log_path": tmp_path / "refresh.log"}))
    with respx.mock() as mock:
        mock.get(_DOWNLOAD_URL).respond(200, content=xlsx.read_bytes())
        with pytest.raises(_EIA860MHardError):
            adapter.fetch(date(2024, 1, 1), date(2024, 12, 31))
