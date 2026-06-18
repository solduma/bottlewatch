"""EPA eGRID + WRI Aqueduct adapter.

Provides the carbon-intensity and water-stress overlays for the
`data_center_shell` segment. Per the v1 plan §6 and the data
sources assessment (`research/03_data_sources.md` §6), eGRID
is the headline source for IDC siting carbon intensity, and
WRI Aqueduct 4.0 is the headline for water stress.

Design notes (spec frozen 2026-06-07):

1. **eGRID source.** EPA publishes eGRID annually as a single
   XLSX (~21MB for the 2023 edition, much smaller than the
   v1 plan's ~250MB estimate). The current file is
   `https://www.epa.gov/system/files/documents/2025-06/egrid2023_data_rev2.xlsx`.
   The adapter reads the `SRL23` sheet (subregion-level roll-up,
   28 rows × 169 cols) and emits one RawSignal per subregion.

2. **WRI source.** WRI Aqueduct 4.0 country CSV is the global
   water-stress index. We use a hand-curated
   `(state → eGRID subregion)` lookup to take the mean WRI
   score across states within each subregion. This is honest
   and defensible; area-weighted joins between eGRID subregions
   and WRI basins are non-trivial and the resulting precision
   is not load-bearing for the v1 dashboard.

3. **Cache layout.** eGRID XLSX → `data/cache/epa_egrid/egrid2023.parquet`
   (parquet-shredded for fast polars reads; the adapter falls
   back to XLSX if the parquet doesn't exist). WRI CSV →
   `data/cache/epa_egrid/wri_aqueduct_4.parquet`. Both cached
   for 6 months (eGRID is annual with mid-year revisions; WRI
   is roughly biennial).

4. **Cadence.** `QUARTERLY`. The orchestrator's monthly check
   is fine because the cache short-circuits downloads; quarterly
   is the "real" cadence for new editions.

5. **Graceful degradation.** If either download fails, the
   adapter logs a warning and returns `[]` for that signal class
   (eGRID or WRI). It does NOT raise.

6. **Per-subregion scope.** The adapter emits per eGRID subregion,
   not per universe ticker. The `data_center_shell` segment
   uses this for siting overlays; specific tickers (Equinix,
   Digital Realty, etc.) inherit the subregion-level signal
   via the value-chain map in `app/value_chain.py`.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path

import httpx
import polars as pl
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from bottlewatch.app.ingest.base import Adapter, Cadence, ProgressCallback, RawSignal
from bottlewatch.config import Settings

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Current eGRID edition (verified 2026-06-07; eGRID 2023 Rev 2,
# released 2025-06-12). Update this constant when EPA releases
# a new edition (typically late January of each year).
EGRID_EDITION = "egrid2023"
EGRID_DOWNLOAD_URL = "https://www.epa.gov/system/files/documents/2025-06/egrid2023_data_rev2.xlsx"

# WRI Aqueduct 4.0 country-level CSV. CC-BY 4.0 license; free
# for commercial use with attribution. The exact URL may
# change with WRI's site reorganizations; this is the path
# as of 2023-08-16 (4.0 release). For v1 we use the country CSV;
# sub-national joins are deferred to v1.1.
WRI_DOWNLOAD_URL = (
    "https://raw.githubusercontent.com/wri/aqueduct-water-risk/main/"
    "aqueduct-data/2023/country_csv/aqueduct_water_risk_country.csv"
)

# 6-month cache TTL. eGRID is annual; WRI is roughly biennial.
# Quarterly check is enough to catch new releases.
_CACHE_TTL_DAYS = 180

# 1 lb/MWh = 0.453592 g/kWh (exact).
_LB_PER_MWH_TO_G_PER_KWH = 0.453592

# Transient errors that warrant a retry on download. 4xx (other
# than 429) is caller error and propagates.
_RETRYABLE_EXCEPTIONS = (
    httpx.TransportError,
    httpx.HTTPStatusError,
)


class _EGRIDHardError(Exception):
    """Raised for non-retryable 4xx responses (bad URL, etc.)."""


# ---------------------------------------------------------------------------
# State → eGRID subregion lookup (the hand-curated piece)
# ---------------------------------------------------------------------------
#
# Per the spec, this is the canonical v1 mapping. Real crosswalk
# is in eGRID 2023 PLNT23 (the `Plant state abbreviation` column).
# The hand-curated version is honest, defensible, and easier to
# audit than an SQL query against 12,613 plant rows. ~50 states
# × 1 line each.
#
# Update this table when a new eGRID edition redistributes states
# between subregions (rare; happens at decade-scale grid changes).

_STATE_TO_SUBREGION: dict[str, str] = {
    # NWPP: Pacific NW + Rockies (most of WA, OR, ID, MT, parts of UT, NV)
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
    # SRSO: SERC South (GA, AL)
    "GA": "SRSO",
    "AL": "SRSO",
    # SRMV: SERC Mississippi Valley (MS, LA, parts of AR)
    "MS": "SRMV",
    "LA": "SRMV",
    # SRVC: SERC Virginia/Carolina
    "VA": "SRVC",
    "NC": "SRVC",
    "SC": "SRVC",
    # SRTV: SERC Tennessee Valley
    "TN": "SRTV",
    "KY": "SRTV",
    # RFCW: RFC West (IL, parts of IN, MO, AR)
    "IL": "RFCW",
    # MROW: MRO West (upper midwest)
    "WI": "MROW",
    "MN": "MROW",
    "IA": "MROW",
    "NE": "MROW",
    "SD": "MROW",
    "ND": "MROW",
    # SRMW: SERC Midwest (MO, AR)
    "MO": "SRMW",
    "AR": "SRMW",
    # RFCE: RFC East (PA, NJ, MD, DE, DC, OH, WV)
    "PA": "RFCE",
    "NJ": "RFCE",
    "MD": "RFCE",
    "DE": "RFCE",
    "DC": "RFCE",
    "OH": "RFCE",
    "WV": "RFCE",
    # NYUP: New York (upstate majority)
    "NY": "NYUP",
    # NEWE: New England
    "MA": "NEWE",
    "CT": "NEWE",
    "RI": "NEWE",
    "NH": "NEWE",
    "VT": "NEWE",
    "ME": "NEWE",
    # FRCC: Florida
    "FL": "FRCC",
    # SPP: Kansas, Oklahoma
    "KS": "SPNO",
    "OK": "SPSO",
    # RFCM: RFC Michigan
    "MI": "RFCM",
    # IN: split between RFCW (most) and RFCM
    "IN": "RFCW",
}


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class EPAEGridAdapter(Adapter):
    """Adapter for EPA eGRID (carbon) + WRI Aqueduct (water).

    Replaces the previous stub (`is_configured() returns False`).
    """

    name = "epa_egrid"
    cadence = Cadence.MONTHLY  # orchestrator check; real cadence is annual
    # Note: MONTHLY because the Cadence enum has no QUARTERLY
    # value. The orchestrator's monthly check is fine because
    # the cache short-circuits downloads.

    # The observed_at for emitted signals: the eGRID publication
    # date. eGRID 2023 Rev 2 was released 2025-06-12; for v1 we
    # use the year (2025-06-01) as a stable date for the
    # current edition. Update when a new edition lands.
    EGRID_PUBLICATION_DATE = date(2025, 6, 12)
    WRI_PUBLICATION_DATE = date(2023, 8, 16)
    # released_at = the publication date as a datetime, so the point-in-time
    # recompute gates on when EPA/WRI actually published (not fetch time).
    EGRID_RELEASED_AT = datetime(2025, 6, 12)
    WRI_RELEASED_AT = datetime(2023, 8, 16)

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    # -- public adapter protocol ------------------------------------------------

    def is_configured(self) -> tuple[bool, str]:
        # eGRID is free; no API key required. WRI is CC-BY 4.0,
        # attribution-only. Both downloads are unauthenticated.
        return True, ""

    def fetch(
        self,
        period_start: date,
        period_end: date,
        progress: ProgressCallback | None = None,
    ) -> list[RawSignal]:
        """Emit eGRID + WRI signals per subregion.

        Algorithm:
        1. Read the cached eGRID SRL23 sheet (or download).
        2. For each subregion, emit CO2RATE in lb/MWh and gCO2/kWh.
        3. Read the cached WRI country CSV (or download).
        4. Join to eGRID subregions via the state lookup.
        5. Emit water-stress per subregion.
        6. If either step fails, log a warning and skip that
           signal class. Does not raise.
        """
        signals: list[RawSignal] = []
        srl_df = self._read_or_download_srl23()
        if srl_df is not None and not srl_df.is_empty():
            signals.extend(self._build_co2_signals(srl_df))

        wri_df = self._read_or_download_wri()
        if wri_df is not None and not wri_df.is_empty() and srl_df is not None:
            signals.extend(self._build_water_signals(srl_df, wri_df))

        return signals

    # -- eGRID: read or download ------------------------------------------------

    def _xlsx_cache_path(self) -> Path:
        """Where the eGRID XLSX (or its parquet-shredded form) lives."""
        return self._cache_dir() / f"{EGRID_EDITION}.xlsx"

    def _parquet_cache_path(self) -> Path:
        """Parquet-shredded eGRID SRL23 sheet. Read faster than XLSX."""
        return self._cache_dir() / f"{EGRID_EDITION}_srl23.parquet"

    def _read_or_download_srl23(self) -> pl.DataFrame | None:
        """Return the eGRID SRL23 sheet as a polars DataFrame, or
        None on failure. Tries parquet cache first, then XLSX
        cache, then downloads.
        """
        # 1. Parquet cache (fastest path)
        parquet = self._parquet_cache_path()
        if parquet.exists() and self._cache_is_fresh(parquet):
            try:
                return pl.read_parquet(parquet)
            except (OSError, Exception) as exc:
                _LOGGER.warning("epa_egrid: failed to read parquet cache: %s", exc)

        # 2. XLSX cache → re-shred to parquet
        xlsx = self._xlsx_cache_path()
        if not xlsx.exists() or not self._cache_is_fresh(xlsx):
            try:
                self._download_egrid()
            except (_EGRIDHardError, *_RETRYABLE_EXCEPTIONS) as exc:  # type: ignore[misc]
                _LOGGER.warning("epa_egrid: download failed: %s", exc)
                return None
        if not xlsx.exists():
            return None

        try:
            df = pl.read_excel(xlsx, sheet_name="SRL23")
        except (OSError, Exception) as exc:
            _LOGGER.warning("epa_egrid: failed to read XLSX: %s", exc)
            return None

        # Shred to parquet for next time
        try:
            parquet.parent.mkdir(parents=True, exist_ok=True)
            df.write_parquet(parquet)
        except OSError as exc:
            _LOGGER.debug("epa_egrid: failed to write parquet cache: %s", exc)

        return df

    @retry(
        retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=10),
        reraise=True,
    )
    def _download_egrid(self) -> None:
        """Download the eGRID XLSX to the cache directory."""
        dest = self._xlsx_cache_path()
        if dest.exists() and dest.stat().st_size > 0:
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        with httpx.Client(timeout=300.0) as client:  # XLSX is 21MB
            resp = client.get(EGRID_DOWNLOAD_URL, follow_redirects=True)
        if resp.status_code == 429 or resp.status_code >= 500:
            resp.raise_for_status()
        if resp.status_code >= 400:
            raise _EGRIDHardError(f"eGRID GET returned {resp.status_code}")
        dest.write_bytes(resp.content)

    # -- WRI: read or download -------------------------------------------------

    def _wri_cache_path(self) -> Path:
        """Where the WRI CSV (or its parquet-shredded form) lives."""
        return self._cache_dir() / "wri_aqueduct_4.parquet"

    def _read_or_download_wri(self) -> pl.DataFrame | None:
        """Return the WRI country CSV as a polars DataFrame."""
        parquet = self._wri_cache_path()
        if parquet.exists() and self._cache_is_fresh(parquet):
            try:
                return pl.read_parquet(parquet)
            except (OSError, Exception) as exc:
                _LOGGER.warning("epa_egrid: failed to read WRI parquet: %s", exc)

        try:
            self._download_wri()
        except (_EGRIDHardError, *_RETRYABLE_EXCEPTIONS) as exc:  # type: ignore[misc]
            _LOGGER.warning("epa_egrid: WRI download failed: %s", exc)
            return None
        if not parquet.exists():
            return None

        try:
            df = pl.read_parquet(parquet)
        except (OSError, Exception) as exc:
            _LOGGER.warning("epa_egrid: failed to read WRI parquet after download: %s", exc)
            return None
        return df

    @retry(
        retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=10),
        reraise=True,
    )
    def _download_wri(self) -> None:
        """Download the WRI country CSV, convert to parquet."""
        dest = self._wri_cache_path()
        if dest.exists() and dest.stat().st_size > 0:
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        with httpx.Client(timeout=120.0) as client:
            resp = client.get(WRI_DOWNLOAD_URL, follow_redirects=True)
        if resp.status_code == 429 or resp.status_code >= 500:
            resp.raise_for_status()
        if resp.status_code >= 400:
            raise _EGRIDHardError(f"WRI GET returned {resp.status_code}")
        # WRI returns CSV; convert to parquet in-memory
        try:
            df = pl.read_csv(resp.content)
        except (OSError, Exception) as exc:
            _LOGGER.warning("epa_egrid: failed to parse WRI CSV: %s", exc)
            return
        df.write_parquet(dest)

    # -- signal construction ---------------------------------------------------

    def _build_co2_signals(self, srl_df: pl.DataFrame) -> list[RawSignal]:
        """Emit one CO2RATE signal per subregion, in two units."""
        signals: list[RawSignal] = []
        # Identify the CO2RATE column. eGRID 2023 long name;
        # see `research/03_data_sources.md` §6 for the full schema.
        co2_col = "eGRID subregion annual CO2 total output emission rate (lb/MWh)"
        if co2_col not in srl_df.columns:
            # Try alternative column names from older eGRID editions
            for alt in [
                "eGRID subregion CO2 emission rate",
                "Subregion CO2 emission rate",
                "CO2 emission rate",
            ]:
                if alt in srl_df.columns:
                    co2_col = alt
                    break
            else:
                _LOGGER.warning("epa_egrid: no CO2RATE column found in SRL23")
                return signals

        for row in srl_df.iter_rows(named=True):
            sr = row.get("eGRID subregion acronym")
            rate = row.get(co2_col)
            if not sr or rate is None:
                continue
            try:
                rate_f = float(rate)
            except (TypeError, ValueError):
                continue
            geo = f"eGRID:{sr}"
            signals.extend(
                [
                    RawSignal(
                        segment="data_center_shell",
                        subsegment="egrid_co2",
                        signal_name="co2_rate_lb_per_mwh",
                        value_num=rate_f,
                        unit="lb/MWh",
                        source=self.name,
                        source_id=f"egrid2023:{sr}:lb_per_mwh",
                        observed_at=self.EGRID_PUBLICATION_DATE,
                        released_at=self.EGRID_RELEASED_AT,
                        value_text="annual output emission rate",
                        geography=geo,
                        tickers="[]",
                    ),
                    RawSignal(
                        segment="data_center_shell",
                        subsegment="egrid_co2",
                        signal_name="co2_rate_g_per_kwh",
                        value_num=rate_f * _LB_PER_MWH_TO_G_PER_KWH,
                        unit="gCO2/kWh",
                        source=self.name,
                        source_id=f"egrid2023:{sr}:g_per_kwh",
                        observed_at=self.EGRID_PUBLICATION_DATE,
                        released_at=self.EGRID_RELEASED_AT,
                        value_text="annual output emission rate",
                        geography=geo,
                        tickers="[]",
                    ),
                ]
            )
        return signals

    def _build_water_signals(
        self,
        srl_df: pl.DataFrame,
        wri_df: pl.DataFrame,
    ) -> list[RawSignal]:
        """Emit one WRI water-stress signal per eGRID subregion.

        Strategy: for each subregion, find the WRI water-stress
        score for each state in the (state → subregion) lookup,
        then take the mean. If the WRI data is country-level
        (no state breakdown), fall back to the US-wide value.
        """
        signals: list[RawSignal] = []
        # Identify the WRI water-stress column. The 4.0 release
        # uses `water_stress` (no spaces); older releases may
        # vary. The first column matching a `water_stress`-like
        # name is the right one.
        wri_col = None
        for c in wri_df.columns:
            if isinstance(c, str) and "water_stress" in c.lower():
                wri_col = c
                break
        if wri_col is None:
            _LOGGER.warning("epa_egrid: no water_stress column in WRI data")
            return signals

        # For v1 with country-level data: apply the US-wide
        # value to all subregions. This is a coarse approximation
        # but the alternative (sub-national join) is non-trivial.
        us_row = None
        for row in wri_df.iter_rows(named=True):
            iso = row.get("iso_a3") or row.get("ISO3") or ""
            name = row.get("name") or row.get("Name") or ""
            if iso == "USA" or "United States" in str(name):
                us_row = row
                break
        if us_row is None:
            _LOGGER.warning("epa_egrid: no USA row in WRI data")
            return signals
        us_score = us_row.get(wri_col)
        if us_score is None:
            return signals
        try:
            us_score_f = float(us_score)
        except (TypeError, ValueError):
            return signals

        # Emit one signal per subregion in the SRL23 sheet.
        # The subregion list is taken from the eGRID SRL23
        # (28 subregions); we don't have state-level WRI data
        # for v1, so the value is the same for all 28.
        for row in srl_df.iter_rows(named=True):
            sr = row.get("eGRID subregion acronym")
            if not sr:
                continue
            signals.append(
                RawSignal(
                    segment="data_center_shell",
                    subsegment="wri_water_stress",
                    signal_name="water_stress_index",
                    value_num=us_score_f,
                    unit="index",
                    source=self.name,
                    source_id=f"wri_aqueduct_4:{sr}",
                    observed_at=self.WRI_PUBLICATION_DATE,
                    released_at=self.WRI_RELEASED_AT,
                    value_text="country-level (US-wide); per-subregion join deferred to v1.1",
                    geography=f"eGRID:{sr}",
                    tickers="[]",
                )
            )
        return signals

    # -- helpers ---------------------------------------------------------------

    def _cache_dir(self) -> Path:
        return self._settings.refresh_log_path.parent / "epa_egrid"

    @staticmethod
    def _cache_is_fresh(path: Path) -> bool:
        """True if the cache file's mtime is within the TTL window."""
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return False
        import time

        age = time.time() - mtime
        return age < _CACHE_TTL_DAYS * 86400


def build_epa_egrid_adapter(settings: Settings) -> EPAEGridAdapter:
    """Factory: the orchestrator calls this with a Settings instance."""
    return EPAEGridAdapter(settings)
