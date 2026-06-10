"""EIA Open Data v2 adapter.

Pins the v2 base URL (per v1 plan §9: "EIA v2 API changes. Pin the API
version; snapshot responses."). Uses `httpx.Client` sync + a
`tenacity` retry decorator that only re-fires on transient failures
(429, 5xx, network errors); 4xx is treated as a hard error and
propagates so the orchestrator can record the `ERROR` status.

The EIA v2 envelope is `{"response": {"data": [...], "total": N}}`.
Each row carries `period` (YYYY-MM-DD or YYYY-MM or YYYY) and a
value column whose name varies by route (`generation`, `sales`, …).
We coerce to float and silently drop non-numeric ones, with a debug
log. Optional columns like `stateid` and `sectorid` are folded into
the `geography` slot of the resulting `RawSignal`.

Two series in M1 (per M1 plan §7), addressed via the v2 `/seriesid/`
bridge so we can refer to them by their v1 ids:

- `ELEC.GEN.ALL-US-99.A` (annual net generation, total US) →
  power_generation_oem / net_gen_twh / TWh
- `ELEC.SALES.TX-RES.M` (monthly TX residential retail sales) →
  data_center_shell / ercot_residential_load_proxy / retail_sales_mwh / MWh
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import httpx
from pydantic import ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from bottlewatch.app.config_loader import load_eia_series_spec
from bottlewatch.app.ingest.base import Adapter, Cadence, ProgressCallback, RawSignal
from bottlewatch.config import Settings

_LOGGER = logging.getLogger(__name__)

# Transient conditions that warrant a retry. 4xx (other than 429) is
# caller error; we don't paper over bad series IDs by retrying.
_RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    httpx.TransportError,
    httpx.HTTPStatusError,
)


class _EIAHardError(Exception):
    """Raised for non-retryable 4xx responses (bad series id, bad key, ...)."""


# Map: (series_id, frequency) -> (segment, signal_name, unit, geography,
#                                     value_column).
# `value_column` is the v2 row field we read; EIA v2 emits different
# names depending on the route (e.g. `value` for some series, `sales`
# for retail, `generation` for power-ops). The series_id is the
# v1-format identifier we hand to the v2 `/seriesid/` bridge.
# The actual list lives in research/config/eia_series_spec.json so
# adding a new series is a one-file JSON edit; `_SERIES_SPEC` here
# is a frozen view of the JSON for import-time access.
_SERIES_SPEC: list[dict[str, Any]] = load_eia_series_spec()


def _coerce_value(raw: Any) -> float | None:
    """EIA v2 emits values as strings, sometimes "<0.001" or "NA". Drop non-numeric."""
    if raw is None:
        return None
    s = str(raw).strip()
    if s == "" or s.upper() == "NA" or s.upper() == "--":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_period(period: str) -> date | None:
    """EIA v2 periods are YYYY, YYYY-MM, or YYYY-MM-DD. Normalize to day-resolution."""
    if not isinstance(period, str):
        return None
    parts = period.split("-")
    try:
        if len(parts) == 1:
            return date(int(parts[0]), 12, 31)
        if len(parts) == 2:
            return date(int(parts[0]), int(parts[1]), 1)
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        return None


class EIAV2Adapter(Adapter):
    """The EIA Open Data v2 adapter. See module docstring for design notes."""

    name = "eia_v2"
    cadence = Cadence.DAILY

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def is_configured(self) -> tuple[bool, str]:
        if not self._settings.eia_api_key:
            return False, "EIA_API_KEY not set"
        return True, ""

    @retry(
        retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=10),
        reraise=True,
    )
    def _get_json(self, client: httpx.Client, series_id: str) -> dict[str, Any]:
        """GET one series, with retry on transient errors. 4xx (non-429) propagates."""
        # Use the v2 /seriesid/ bridge so we can refer to series by the
        # legacy v1 id (e.g. ELEC.GEN.ALL-US-99.A). The bridge figures
        # out the right route + facets from the id.
        #
        # The bridge does not honor start/end params (returns the full
        # series); the orchestrator's window is applied client-side in
        # `_parse_series` so backfills are bounded. A future refactor
        # could switch to the native v2 route per series and let EIA
        # filter server-side.
        url = f"{self._settings.eia_base_url}/seriesid/{series_id}"
        params: dict[str, str | int] = {
            "api_key": self._settings.eia_api_key or "",
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
            "length": 5000,
        }
        resp = client.get(url, params=params)
        # 4xx other than 429 -> hard error (not retried). 429 + 5xx ->
        # raise HTTPStatusError so tenacity retries.
        if resp.status_code == 429 or resp.status_code >= 500:
            resp.raise_for_status()
        if resp.status_code >= 400:
            raise _EIAHardError(f"EIA v2 {series_id} returned {resp.status_code}: {resp.text[:200]}")
        return resp.json()  # type: ignore[no-any-return]

    def _parse_series(
        self,
        spec: dict[str, Any],
        body: dict[str, Any],
        period_start: date,
        period_end: date,
    ) -> list[RawSignal]:
        rows: list[RawSignal] = []
        value_column = spec.get("value_column", "value")
        for raw_row in body.get("response", {}).get("data", []):
            # `period` comes back as a string OR an int (annual
            # generation returns `2025` as a JSON number; monthly
            # returns "2025-03" as a string). Normalize to str.
            period_raw = raw_row.get("period", "")
            period = _parse_period(str(period_raw))
            if period is None or period < period_start or period > period_end:
                continue
            value = _coerce_value(raw_row.get(value_column))
            if value is None:
                continue
            try:
                rows.append(
                    RawSignal(
                        segment=spec["segment"],
                        subsegment=spec.get("subsegment"),
                        signal_name=spec["signal_name"],
                        value_num=value,
                        unit=spec["unit"],
                        geography=spec["geography"],
                        source=self.name,
                        source_id=spec["series_id"],
                        observed_at=period,
                    )
                )
            except ValidationError:
                # Pydantic forbid-extras guards against unexpected column drift.
                _LOGGER.debug("dropped malformed row for %s: %r", spec["series_id"], raw_row)
        return rows

    def fetch(
        self,
        period_start: date,
        period_end: date,
        progress: ProgressCallback | None = None,
    ) -> list[RawSignal]:
        ok, reason = self.is_configured()
        if not ok:
            _LOGGER.info("EIA v2: %s; skipping fetch", reason)
            return []
        results: list[RawSignal] = []
        with httpx.Client(timeout=self._settings.eia_timeout_s) as client:
            for spec in _SERIES_SPEC:
                # _get_json() retries transient errors itself; anything
                # that escapes is a real failure (hard 4xx, all retries
                # exhausted) and should bubble up to the orchestrator.
                body = self._get_json(client, spec["series_id"])
                results.extend(self._parse_series(spec, body, period_start, period_end))
        return results


def build_eia_v2_adapter(settings: Settings) -> EIAV2Adapter:
    """Factory: the orchestrator calls this with a Settings instance."""
    return EIAV2Adapter(settings)
