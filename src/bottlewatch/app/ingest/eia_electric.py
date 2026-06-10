"""EIA Electric adapter.

Fetches national industrial retail sales from the EIA v2
`seriesid` bridge (the same bridge the EIAV2Adapter uses). The
native v2 `/electricity/retail-sales` route returns only a schema
description; the actual observations come through the bridge
with the v1 series id (e.g. `ELEC.SALES.ALL-US-IND.M`).

The industrial sector's kWh sales nationally is a forward-looking
demand proxy for data center power: when industrial sales trend
up, the grid is constrained, and the data_center_shell segment
becomes more binding.

For M1 this adapter was a stub that returned one fake signal.
That stub is replaced with a real fetch. The `data_center_shell`
extractor does NOT read `retail_sales_industrial` (it reads
`retail_sales_mwh` from EIA v2's TX-RES series). This adapter
adds a second, distinct signal that the scoreboard can surface
on the segment detail page as additional context.
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

from bottlewatch.app.ingest.base import Adapter, Cadence, ProgressCallback, RawSignal
from bottlewatch.config import Settings

_LOGGER = logging.getLogger(__name__)

# Transient conditions that warrant a retry. 4xx (other than 429) is
# caller error; we don't paper over bad series IDs or a bad key by retrying.
_RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    httpx.TransportError,
    httpx.HTTPStatusError,
)


class _EIAElectricHardError(Exception):
    """Raised for non-retryable 4xx responses (bad key, bad series id, ...)."""


# v1-format series id for national industrial retail sales. The
# v2 bridge (`/seriesid/<id>`) translates this into the right
# route + facets. The bridge does not honor start/end params
# (returns the full series); the orchestrator's per-row filter
# (in _parse_series) bounds the result.
_SERIES_ID = "ELEC.SALES.US-IND.M"


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
    """EIA v2 monthly periods are YYYY-MM. Normalize to the first of the month."""
    if not isinstance(period, str):
        return None
    parts = period.split("-")
    if len(parts) != 2:
        return None
    try:
        return date(int(parts[0]), int(parts[1]), 1)
    except (ValueError, IndexError):
        return None


class EIAElectricAdapter(Adapter):
    """EIA v2 retail-sales adapter for national industrial kWh."""

    name = "eia_electric"
    cadence = Cadence.MONTHLY

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
    def _get_json(self, client: httpx.Client) -> dict[str, Any]:
        """GET one series via the v1-id bridge, with retry on transient errors.

        4xx (other than 429) propagates as a hard error so the
        orchestrator can record it as `ERROR` (not silently 0 rows).
        """
        url = f"{self._settings.eia_base_url}/seriesid/{_SERIES_ID}"
        params: dict[str, str | int] = {
            "api_key": self._settings.eia_api_key or "",
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
            "length": 5000,
        }
        resp = client.get(url, params=params)
        if resp.status_code == 429 or resp.status_code >= 500:
            resp.raise_for_status()
        if resp.status_code >= 400:
            raise _EIAElectricHardError(f"EIA v2 {_SERIES_ID} returned {resp.status_code}: {resp.text[:200]}")
        return resp.json()  # type: ignore[no-any-return]

    def _parse_series(
        self,
        body: dict[str, Any],
        period_start: date,
        period_end: date,
    ) -> list[RawSignal]:
        rows: list[RawSignal] = []
        for raw_row in body.get("response", {}).get("data", []):
            period_raw = raw_row.get("period", "")
            period = _parse_period(str(period_raw))
            if period is None or period < period_start or period > period_end:
                continue
            # `sales` is in million kWh per EIA v2 docs.
            value = _coerce_value(raw_row.get("sales"))
            if value is None:
                continue
            try:
                rows.append(
                    RawSignal(
                        segment="data_center_shell",
                        signal_name="retail_sales_industrial",
                        value_num=value,
                        unit="million_kWh",
                        geography="US-IND",
                        source=self.name,
                        source_id=str(period_raw),
                        observed_at=period,
                    )
                )
            except ValidationError:
                # Pydantic forbid-extras guards against unexpected column drift.
                _LOGGER.debug("dropped malformed row: %r", raw_row)
        return rows

    def fetch(
        self,
        period_start: date,
        period_end: date,
        progress: ProgressCallback | None = None,
    ) -> list[RawSignal]:
        ok, reason = self.is_configured()
        if not ok:
            _LOGGER.info("EIA Electric: %s; skipping fetch", reason)
            return []
        # The orchestrator's monthly-cadence window is `first_of_prev_month`
        # to `today` — too narrow to capture the 24 months of
        # history the recompute job needs for YoY deltas. Override
        # to a 2-year window that matches the recompute's signal
        # window. The orchestrator's per-row filter on
        # `period_start`/`period_end` (passed through to
        # `_parse_series`) still bounds the result, so if the user
        # runs with --since=2025-01-01, only 2025+ rows are kept.
        if (period_end - period_start).days < 365:
            period_start = period_end.replace(year=period_end.year - 2)
        with httpx.Client(timeout=self._settings.eia_timeout_s) as client:
            body = self._get_json(client)
        return self._parse_series(body, period_start, period_end)


def build_eia_electric_adapter(settings: Settings) -> EIAElectricAdapter:
    """Factory: the orchestrator calls this with a Settings instance."""
    return EIAElectricAdapter(settings)
