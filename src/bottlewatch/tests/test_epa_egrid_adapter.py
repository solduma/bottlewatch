"""Tests for the EPA eGRID + WRI Aqueduct adapter.

Spec (2026-06-07): The adapter
1. Pulls the latest eGRID XLSX (eGRID 2023 Rev 2, 21.2MB) on a
   6-month cadence. Caches the file under
   `data/cache/epa_egrid/`.
2. Parses the `SRL23` sheet (subregion-level) and emits one signal
   per eGRID subregion (28 total) with the CO2RATE column
   (in both lb/MWh and gCO2/kWh).
3. Pulls the WRI Aqueduct 4.0 country CSV, joins to eGRID
   subregions via a hand-curated (state → subregion) lookup,
   and emits a water-stress signal per subregion.
4. Feeds the `data_center_shell` segment.

The tests use mocked XLSX (parquet-shaped) responses so they
don't hit the real EPA/WRI servers. Real-world verification is
out of scope for unit tests.

Spec: v1 plan §6.6 + research/03_data_sources.md §6.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
import respx

from bottlewatch.app.ingest import EPAEGridAdapter
from bottlewatch.app.ingest.base import RawSignal
from bottlewatch.app.ingest.epa_egrid import build_epa_egrid_adapter
from bottlewatch.config import Settings


# eGRID 2023 Rev 2 SRL23 sheet shape (verified 2026-06-07 from the
# actual file). Each row is one eGRID subregion with 169 columns.
# We emit per subregion, so the test fixture has 28 rows.
EGRID_DOWNLOAD_URL = "https://www.epa.gov/system/files/documents/2025-06/egrid2023_data_rev2.xlsx"
WRI_DOWNLOAD_URL = "https://raw.githubusercontent.com/wri/aqueduct-water-risk/main/aqueduct-data/2023/country_csv/aqueduct_water_risk_country.csv"


def _srl23_fixture() -> list[dict[str, Any]]:
    """28 rows of SRL23, one per eGRID subregion. Only the columns
    we use are populated; the rest can be empty for testing.
    Column names are the long English names from eGRID 2023.
    """
    subregions = [
        "NYUP",
        "CAMX",
        "NEWE",
        "RFCE",
        "SRVC",
        "NWPP",
        "AZNM",
        "SRMV",
        "ERCT",
        "FRCC",
        "SRSO",
        "SPNO",
        "SPSO",
        "NYCW",
        "SRTV",
        "AKGD",
        "RFCW",
        "MROW",
        "RFCM",
        "RMPA",
        "HIMS",
        "NYLI",
        "SRMW",
        "MROE",
        "HIOA",
        "PRMS",
        "AKMS",
        "TECR",
    ]
    # Hand-picked CO2RATE values (lb/MWh) roughly matching the
    # real eGRID 2023 distribution (NYUP cleanest, PRMS dirtiest).
    co2rates = [
        242.089,
        428.464,
        539.275,
        596.904,
        593.419,
        631.735,
        703.703,
        739.720,
        733.862,
        782.262,
        842.329,
        861.999,
        872.042,
        864.469,
        898.079,
        899.633,
        911.424,
        920.130,
        970.617,
        1036.601,
        1123.371,
        1180.672,
        1239.839,
        1397.313,
        1489.548,
        1543.073,
        850.000,
        800.000,
    ]
    return [
        {
            "eGRID subregion acronym": sr,
            "eGRID subregion annual CO2 total output emission rate (lb/MWh)": rate,
        }
        for sr, rate in zip(subregions, co2rates)
    ]


def _wri_fixture() -> list[dict[str, Any]]:
    """WRI Aqueduct 4.0 country CSV. We use US-only. The fixture
    has one row per US state with a water-stress score.
    """
    # Real WRI scores are 0-5 (higher = more stressed). These are
    # realistic placeholders; the real values are similar.
    return [
        {"name": "United States", "water_stress": 2.83, "iso_a3": "USA"},
        {"name": "Canada", "water_stress": 1.21, "iso_a3": "CAN"},
        {"name": "Mexico", "water_stress": 3.45, "iso_a3": "MEX"},
    ]


# State → eGRID subregion lookup (the hand-curated piece).
# Mirror of the real mapping; the v1 plan claims the crosswalk
# is derivable from PLNT23. For the v1 hand-curated approach,
# this is the canonical list. Real mapping is in eGRID 2023 PLNT23.
_STATE_TO_SUBREGION: dict[str, str] = {
    # NWPP: Pacific NW + Rockies
    "WA": "NWPP",
    "OR": "NWPP",
    "ID": "NWPP",
    "MT": "NWPP",
    "WY": "RMPA",
    "CO": "RMPA",
    "UT": "NWPP",
    "NV": "NWPP",
    # CAMX: California
    "CA": "CAMX",
    # AZNM: Arizona + New Mexico
    "AZ": "AZNM",
    "NM": "AZNM",
    # ERCT: Texas
    "TX": "ERCT",
    # SRSO: SERC South
    "GA": "SRSO",
    "AL": "SRSO",
    "MS": "SRMV",
    "LA": "SRMV",
    # SRVC: SERC Virginia/Carolina
    "VA": "SRVC",
    "NC": "SRVC",
    "SC": "SRVC",
    # SRTV: SERC Tennessee Valley
    "TN": "SRTV",
    "KY": "SRTV",
    # RFCW: RFC West
    "IL": "RFCW",
    "WI": "MROW",
    "MN": "MROW",
    "IA": "MROW",
    "MO": "SRMW",
    "AR": "SRMW",
    # RFCE: RFC East
    "PA": "RFCE",
    "NJ": "RFCE",
    "MD": "RFCE",
    "DE": "RFCE",
    "DC": "RFCE",
    # NYCW + NYLI + NYUP: New York
    "NY": "NYUP",  # majority is upstate; downstate split would be more granular
    # NEWE: New England
    "MA": "NEWE",
    "CT": "NEWE",
    "RI": "NEWE",
    "NH": "NEWE",
    "VT": "NEWE",
    "ME": "NEWE",
    # FRCC: Florida
    "FL": "FRCC",
    # SPP: Kansas, Oklahoma, etc.
    "KS": "SPNO",
    "OK": "SPSO",
    "NE": "MROW",
    "SD": "MROW",
    "ND": "MROW",
    # MROE / MROW: upper midwest
    "IN": "RFCW",
    "OH": "RFCE",
    "MI": "RFCM",
    # Misc
    "WV": "RFCW",
}


@pytest.fixture
def adapter(settings: Settings, tmp_path: Path) -> EPAEGridAdapter:
    """A configured adapter with a tmp cache directory."""
    s = Settings(
        app_env=settings.app_env,
        database_url=settings.database_url,
        refresh_log_path=tmp_path / "refresh.log",
    )
    return build_epa_egrid_adapter(s)


# ---------------------------------------------------------------------------
# is_configured: now True (the adapter is real)
# ---------------------------------------------------------------------------


def test_epa_egrid_is_configured(adapter: EPAEGridAdapter) -> None:
    """The adapter is real; is_configured returns (True, '')."""
    ok, reason = adapter.is_configured()
    assert ok is True, reason
    assert reason == ""


# ---------------------------------------------------------------------------
# Happy path: 28 subregions, CO2RATE in both units
# ---------------------------------------------------------------------------


def _populate_parquet_cache(adapter: EPAEGridAdapter, fixture: list[dict]) -> Path:
    """Write a polars DataFrame to the adapter's expected
    parquet cache location, simulating a successful prior
    download.
    """
    import polars as pl

    cache = adapter._parquet_cache_path()
    cache.parent.mkdir(parents=True, exist_ok=True)
    df = pl.DataFrame(fixture)
    df.write_parquet(cache)
    return cache


def _co2(signals: list[RawSignal]) -> list[RawSignal]:
    """Filter signals to eGRID CO2 emissions. The cast silences
    pyright's `reportOptionalMemberAccess` on `s.subsegment`
    (the iteration var loses its `RawSignal` type through
    list-comprehension).
    """
    return [s for s in signals if s.subsegment == "egrid_co2"]


def _water(signals: list[RawSignal]) -> list[RawSignal]:
    """Filter signals to WRI water-stress. See `_co2`."""
    return [s for s in signals if s.subsegment == "wri_water_stress"]


def test_fetch_emits_28_subregion_signals(
    adapter: EPAEGridAdapter,
) -> None:
    """eGRID 2023 has 28 subregions. The adapter emits 28
    CO2RATE signals (one per subregion, lb/MWh unit) and 28
    gCO2/kWh signals. Total: 56.
    """
    _populate_parquet_cache(adapter, _srl23_fixture())

    signals = adapter.fetch(date(2026, 1, 1), date(2026, 12, 31))

    co2_signals = _co2(signals)
    assert len(co2_signals) == 56  # 28 lb/MWh + 28 gCO2/kWh

    # Spot-check the cleanest subregion
    nyup = [s for s in co2_signals if "NYUP" in (s.geography or "")]
    assert len(nyup) == 2
    for s in nyup:
        assert s.segment == "data_center_shell"
        assert s.source == "epa_egrid"
        assert s.value_num is not None
        # CO2RATE for NYUP is ~242 lb/MWh (~110 gCO2/kWh)
        if s.unit == "lb/MWh":
            assert s.value_num == pytest.approx(242.089, abs=0.01)
        else:
            assert s.unit == "gCO2/kWh"
            # 242.089 lb/MWh = 109.86 gCO2/kWh
            assert s.value_num == pytest.approx(109.86, abs=0.5)


def test_subregion_28_rows_in_cache_emits_exactly_28_unique_subregions(
    adapter: EPAEGridAdapter,
) -> None:
    """Spec: one signal per subregion. With 28 rows in the SRL23
    sheet, we should see 28 unique geographies.
    """
    _populate_parquet_cache(adapter, _srl23_fixture())

    signals = adapter.fetch(date(2026, 1, 1), date(2026, 12, 31))
    co2_lb = [s for s in _co2(signals) if s.unit == "lb/MWh"]
    geographies = {s.geography for s in co2_lb}
    assert len(geographies) == 28
    # All geographies use the eGRID:<subregion> format.
    for geo in geographies:
        assert geo is not None
        assert geo.startswith("eGRID:")


# ---------------------------------------------------------------------------
# WRI water-stress: per-subregion join via hand-curated state lookup
# ---------------------------------------------------------------------------


def test_wri_water_stress_emits_per_subregion(
    adapter: EPAEGridAdapter,
) -> None:
    """The WRI water-stress signal is per eGRID subregion. The
    adapter uses a hand-curated state→subregion lookup to
    take the mean WRI water-stress across states in each
    subregion. With the fixture (no real state-level data),
    the adapter uses the country-level US value for all
    subregions that have at least one state in the lookup.
    """
    _populate_parquet_cache(adapter, _srl23_fixture())
    # Also write the WRI cache
    import polars as pl

    wri_cache = adapter._wri_cache_path()
    wri_cache.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(_wri_fixture()).write_parquet(wri_cache.with_suffix(".parquet"))

    signals = adapter.fetch(date(2026, 1, 1), date(2026, 12, 31))
    water_signals = _water(signals)
    assert len(water_signals) > 0
    for s in water_signals:
        assert s.segment == "data_center_shell"
        assert s.source == "epa_egrid"
        assert s.signal_name == "water_stress_index"
        assert s.value_num is not None
        assert 0 <= s.value_num <= 5  # WRI's standard scale


# ---------------------------------------------------------------------------
# Cache behavior: re-fetch is a no-op (immutable inputs)
# ---------------------------------------------------------------------------


def test_repeated_fetch_is_idempotent(
    adapter: EPAEGridAdapter,
) -> None:
    """A second fetch within the same window reads the cache
    and produces the same signals. The XLSX and WRI CSV are
    immutable between editions.
    """
    _populate_parquet_cache(adapter, _srl23_fixture())
    import polars as pl

    wri_cache = adapter._wri_cache_path()
    wri_cache.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(_wri_fixture()).write_parquet(wri_cache.with_suffix(".parquet"))

    first = adapter.fetch(date(2026, 1, 1), date(2026, 12, 31))
    second = adapter.fetch(date(2026, 1, 1), date(2026, 12, 31))
    assert len(first) == len(second)
    for a, b in zip(sorted(first, key=lambda s: s.source_id or ""), sorted(second, key=lambda s: s.source_id or "")):
        assert a.source_id == b.source_id
        assert a.value_num == b.value_num


# ---------------------------------------------------------------------------
# Graceful degradation: missing XLSX → empty list, no raise
# ---------------------------------------------------------------------------


def test_missing_xlsx_returns_empty_list(
    adapter: EPAEGridAdapter,
) -> None:
    """If the XLSX is not on disk and the download fails, the
    adapter returns an empty list and logs a warning. It does
    NOT raise.

    Pre-populate the WRI cache so the test only exercises the
    eGRID-failure path; the WRI cache hit short-circuits WRI
    download and we don't accidentally fail the WRI step.
    """
    import polars as pl

    wri_cache = adapter._wri_cache_path()
    wri_cache.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(_wri_fixture()).write_parquet(wri_cache)

    with respx.mock(assert_all_called=False) as mock:
        mock.get(EGRID_DOWNLOAD_URL).respond(503, text="EPA is down")
        signals = adapter.fetch(date(2026, 1, 1), date(2026, 12, 31))

    assert signals == []


def test_wri_missing_does_not_break_co2(
    adapter: EPAEGridAdapter,
) -> None:
    """If the WRI CSV is missing but the eGRID XLSX is present,
    the adapter still emits the CO2RATE signals (56) but
    skips the water-stress signals.
    """
    _populate_parquet_cache(adapter, _srl23_fixture())
    # WRI cache is NOT populated; mock its download to fail.
    with respx.mock(assert_all_called=False) as mock:
        mock.get().respond(503, text="WRI is down")
        signals = adapter.fetch(date(2026, 1, 1), date(2026, 12, 31))

    co2_signals = _co2(signals)
    water_signals = _water(signals)
    assert len(co2_signals) == 56
    assert water_signals == []


# ---------------------------------------------------------------------------
# Unit conversion: 1 lb/MWh ≈ 0.453592 g/kWh
# ---------------------------------------------------------------------------


def test_lb_per_mwh_to_g_per_kwh_conversion(
    adapter: EPAEGridAdapter,
) -> None:
    """Spec: gCO2/kWh = lb/MWh × 0.453592. Spot-check the
    conversion on a known value.
    """
    _populate_parquet_cache(adapter, _srl23_fixture())

    signals = adapter.fetch(date(2026, 1, 1), date(2026, 12, 31))
    # NYUP: 242.089 lb/MWh → 109.86 gCO2/kWh
    nyup_lb = [
        s for s in signals if s.subsegment == "egrid_co2" and s.unit == "lb/MWh" and (s.geography or "") == "eGRID:NYUP"
    ]
    nyup_g = [
        s
        for s in signals
        if s.subsegment == "egrid_co2" and s.unit == "gCO2/kWh" and (s.geography or "") == "eGRID:NYUP"
    ]
    assert len(nyup_lb) == 1
    assert len(nyup_g) == 1
    expected = (nyup_lb[0].value_num or 0.0) * 0.453592
    assert nyup_g[0].value_num == pytest.approx(expected, abs=0.1)
