"""EIA-860M planned-additions adapter.

The EIA v2 API only exposes the *operating* generator inventory
(`status=OP/OS/SB/OA`) — it does not include planned or under-
construction units. The §7.3 resolution-ETA model needs planned
additions, which EIA publishes as a monthly XLSX file ("EIA-860M")
at https://www.eia.gov/electricity/data/eia860m/.

This adapter:
1. Downloads the latest 860M XLSX to `data/cache/eia860m/` (idempotent
   re-runs skip the download).
2. Parses the `Planned` tab with polars (fastexcel backend).
3. Emits one `RawSignal` per planned generator with
   `(state, prime_mover_code, energy_source_code, nameplate_mw,
     planned_operation_year_month)`.

No API key is required (the file is public). `is_configured()` always
returns `(True, "")`. The adapter is `MONTHLY` cadence; the orchestrator's
default lookback covers a single month since the data is point-in-time
inventory, not a time series.

For v1.1 we emit raw per-row signals. M2's scoring engine can aggregate
to `(state × prime_mover × planned_year)` for the §7.3 ETA.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin

import httpx
import polars as pl
from pydantic import ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from bottlewatch.app.ingest.base import Adapter, Cadence, ProgressCallback, RawSignal, quiet_httpx_request_log
from bottlewatch.config import Settings

_LOGGER = logging.getLogger(__name__)

# Public download base. The current-year URL pattern is
# `https://www.eia.gov/electricity/data/eia860m/xls/<month>_generator<year>.xlsx`
# (verified 2026-06; older years live under `/archive/xls/` but the
# orchestrator only ever wants the latest release, which is the
# current year).
_DOWNLOAD_BASE = "https://www.eia.gov/electricity/data/eia860m/xls/"

# Transient conditions that warrant a retry. The XLSX endpoint is just
# a static file on a CDN; 5xx and network errors are retryable, 4xx is not.
_RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    httpx.TransportError,
    httpx.HTTPStatusError,
)

_MONTH_NAMES = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)


def _latest_release_month(today: date) -> tuple[int, int]:
    """Return (year, month) of the latest 860M release. Observed lag is
    ~5 weeks; for safety, walk back two months. June → April, etc.
    """
    year, month = today.year, today.month
    month -= 2
    while month <= 0:
        month += 12
        year -= 1
    return year, month


def _url_for(year: int, month: int) -> str:
    filename = f"{_MONTH_NAMES[month - 1]}_generator{year}.xlsx"
    return urljoin(_DOWNLOAD_BASE, filename)


def _cache_path(settings: Settings, year: int, month: int) -> Path:
    """Where to stash the XLSX. Caching is keyed on the release month so
    a re-run with the same `(today, cadence)` is a no-op download.
    """
    cache_dir = settings.refresh_log_path.parent / "eia860m"
    return cache_dir / f"{_MONTH_NAMES[month - 1]}_generator{year}.xlsx"


class _EIA860MHardError(Exception):
    """Raised for non-retryable 4xx responses (bad URL, etc.)."""


class EIA860MAdapter(Adapter):
    """EIA-860M planned-additions ingest (XLSX download)."""

    name = "eia_860m"
    cadence = Cadence.MONTHLY  # 860M is published monthly; the underlying data
    # is a point-in-time snapshot of the planned inventory, not a time series.

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def is_configured(self) -> tuple[bool, str]:
        # No API key; the XLSX is public.
        return True, ""

    @retry(
        retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=10),
        reraise=True,
    )
    def _download(self, client: httpx.Client, url: str, dest: Path) -> None:
        if dest.exists() and dest.stat().st_size > 0:
            _LOGGER.debug("860M cache hit: %s", dest)
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        with client.stream("GET", url, follow_redirects=True) as resp:
            if resp.status_code == 429 or resp.status_code >= 500:
                resp.raise_for_status()
            if resp.status_code >= 400:
                raise _EIA860MHardError(f"EIA 860M GET {url} returned {resp.status_code}")
            with dest.open("wb") as f:
                for chunk in resp.iter_bytes():
                    f.write(chunk)

    def _parse_planned_rows(self, xlsx_path: Path) -> list[dict[str, str]]:
        """Read the `Planned` tab, skip the 2 title rows (title + blank),
        return the data as a list of dicts keyed by the row-3 column names.
        polars handles type coercion lazily; we coerce to string and let
        `_row_to_signal` handle numeric parsing so a malformed cell drops
        the row instead of failing the whole file.

        `drop_empty_rows=False` keeps the 2 leading rows that 860M uses
        (a title in row 1 and a fully blank row 2). With the default
        `True`, fastexcel strips the blank row and the indices shift.
        """
        raw = pl.read_excel(xlsx_path, sheet_name="Planned", has_header=False, drop_empty_rows=False)
        if raw.height < 4:
            raise _EIA860MHardError(f"860M Planned tab too short: {raw.height} rows")
        header_row = raw.row(2)  # 0-indexed: title, blank, header
        data = raw[3:]
        cols = [str(c) if c is not None else f"col_{i}" for i, c in enumerate(header_row)]
        data = data.rename(dict(zip(raw.columns, cols)))
        # Coerce all values to str so the per-row parser can handle them
        # uniformly. Use `cast(pl.String, strict=False)` so None becomes "".
        rows = data.with_columns([pl.col(c).cast(pl.String, strict=False).alias(c) for c in cols])
        return rows.to_dicts()  # type: ignore[no-any-return]

    def _row_to_signal(self, row: dict[str, str], release_year: int, release_month: int) -> RawSignal | None:
        """Map one 860M Planned row to a RawSignal. Returns None if the
        row lacks a usable year/state/capacity (e.g. status 'T' with no
        planned operation year yet).
        """
        state = (row.get("Plant State") or "").strip()
        capacity_str = (row.get("Nameplate Capacity (MW)") or "").strip()
        planned_year = (row.get("Planned Operation Year") or "").strip()
        if not state or not capacity_str or not planned_year:
            return None
        try:
            capacity_mw = float(capacity_str)
            year = int(planned_year)
        except ValueError:
            return None
        # The Planned Operation Month is often blank or invalid early
        # in the regulatory cycle; fall back to the release month.
        month_str = (row.get("Planned Operation Month") or "").strip()
        try:
            month = int(month_str) if month_str else release_month
            if not 1 <= month <= 12:
                month = release_month
        except ValueError:
            month = release_month
        try:
            observed = date(year, month, 1)
        except ValueError:
            return None
        prime_mover = (row.get("Prime Mover Code") or "").strip() or "UNK"
        energy_source = (row.get("Energy Source Code") or "").strip()
        entity_id = (row.get("Entity ID") or "").strip()
        plant_id = (row.get("Plant ID") or "").strip()
        gen_id = (row.get("Generator ID") or "").strip()
        status = (row.get("Status") or "").strip()
        source_id = f"eia860m:{entity_id}:{plant_id}:{gen_id}"
        try:
            return RawSignal(
                segment="power_generation_oem",
                subsegment=f"planned:{prime_mover}:{energy_source}" if energy_source else f"planned:{prime_mover}",
                signal_name="planned_capacity_mw",
                value_num=capacity_mw,
                unit="MW",
                geography=f"US-{state}",
                source=self.name,
                source_id=source_id,
                observed_at=observed,
                released_at=datetime(release_year, release_month, 1),
                value_text=status or None,
            )
        except ValidationError:
            _LOGGER.debug("dropped malformed 860M row %s", source_id)
            return None

    def fetch(
        self,
        period_start: date,
        period_end: date,
        progress: ProgressCallback | None = None,
    ) -> list[RawSignal]:
        del period_start, period_end  # window is "latest release", not the orchestrator's range
        year, month = _latest_release_month(date.today())
        url = _url_for(year, month)
        cache = _cache_path(self._settings, year, month)
        quiet_httpx_request_log()  # cache hit → no log line; otherwise httpx is already quiet
        with httpx.Client(timeout=self._settings.eia_timeout_s) as client:
            self._download(client, url, cache)

        rows = self._parse_planned_rows(cache)
        signals: list[RawSignal] = []
        for row in rows:
            sig = self._row_to_signal(row, year, month)
            if sig is not None:
                signals.append(sig)
        if not signals:
            raise _EIA860MHardError(f"860M Planned tab produced 0 signals from {cache}")
        _LOGGER.info("EIA-860M: %d planned-addition signals from %s", len(signals), cache.name)
        return signals


def build_eia_860m_adapter(settings: Settings) -> EIA860MAdapter:
    """Factory: the orchestrator calls this with a Settings instance."""
    return EIA860MAdapter(settings)
