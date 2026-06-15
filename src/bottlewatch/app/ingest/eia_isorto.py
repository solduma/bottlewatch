"""EIA ISO/RTO (EIA-930) adapter.

Spec
----
- Load daily, region-level grid data from EIA v2
  `/electricity/rto/daily-region-data/data/` for configured ISO/RTO
  respondents. We use daily aggregates rather than raw hourly to stay
  under the 5 000-row pagination limit while still capturing monthly
  peaks.
- Load nameplate capacity by EIA state (`operating-generator-capacity`)
  and map states to ISO/RTO regions using a static table.
- Emit per-region, per-segment signals:
  * `iso_peak_load_mw`     - monthly peak demand (type=D)
  * `iso_net_generation_mwh` - monthly net generation (type=NG)
  * `iso_capacity_mw`      - latest-month nameplate capacity
- `capacity_tightness` in `extractors.py` consumes `iso_peak_load_mw`
  and `iso_capacity_mw` when available; otherwise it keeps the existing
  power-ratio / retail-sales fallbacks.

What this does NOT do
---------------------
- No live hourly modeling; monthly peaks are sufficient for the
  capacity-tightness sub-score.
- No capacity interconnection queues or transmission constraints.
- No fuel-type breakdown (NG data is stored as an aggregate).
"""

from __future__ import annotations

import logging
from collections import defaultdict
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

# States are mapped to a primary ISO/RTO for capacity aggregation.
# This is a deliberate simplification: states that straddle multiple
# RTOs (e.g. IL, IN) are assigned to the most load-relevant RTO for
# bottleneck monitoring.
_REGION_TO_STATES: dict[str, tuple[str, ...]] = {
    "ERCO": ("TX",),
    "CISO": ("CA",),
    "PJM": (
        "PA",
        "NJ",
        "MD",
        "DE",
        "DC",
        "VA",
        "WV",
        "OH",
        "NC",
        "SC",
        "IL",
        "IN",
        "KY",
        "TN",
        "MI",
    ),
    "MISO": (
        "MN",
        "WI",
        "IA",
        "MO",
        "AR",
        "LA",
        "ND",
        "SD",
        "NE",
        "MS",
        "MT",
        "OK",
        "NM",
        "KS",
        "TX",
    ),
    "NYIS": ("NY",),
    "ISNE": ("ME", "NH", "VT", "MA", "RI", "CT"),
    "SWPP": ("KS", "OK", "NE", "ND", "SD", "MT", "WY", "CO", "NM", "TX"),
}

# Region -> scoring segments. Power sees all monitored regions;
# data-center shell focuses on the high-hyperscaler-load regions.
_REGION_TO_SEGMENTS: dict[str, tuple[str, ...]] = {
    "ERCO": ("power_generation_oem", "data_center_shell"),
    "CISO": ("power_generation_oem", "data_center_shell"),
    "PJM": ("power_generation_oem", "data_center_shell"),
    "MISO": ("power_generation_oem",),
    "NYIS": ("power_generation_oem",),
    "ISNE": ("power_generation_oem",),
    "SWPP": ("power_generation_oem",),
}

_PAGE_SIZE = 5000
_RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    httpx.TransportError,
    httpx.HTTPStatusError,
)


class _EIAISORTOHardError(Exception):
    """Raised for non-retryable 4xx responses."""


def _configured_regions(settings: Settings) -> tuple[str, ...]:
    """Regions enabled for this run; defaults to the curated subset."""
    regions = settings.eia_isorto_regions
    return tuple(r for r in regions if r in _REGION_TO_STATES)


def _region_segments(region: str, settings: Settings) -> tuple[str, ...]:
    """Scoring segments that consume data for this region."""
    if region not in _configured_regions(settings):
        return ()
    return _REGION_TO_SEGMENTS.get(region, ("power_generation_oem",))


def _states_for_regions(regions: tuple[str, ...]) -> tuple[str, ...]:
    """Union of states covered by the enabled regions."""
    seen: set[str] = set()
    for region in regions:
        for state in _REGION_TO_STATES.get(region, ()):
            seen.add(state)
    return tuple(sorted(seen))


def _coerce_value(raw: Any) -> float | None:
    """EIA v2 emits values as strings; drop non-numeric or tiny values."""
    if raw is None:
        return None
    s = str(raw).strip()
    if s == "" or s.upper() in {"NA", "--", "NULL"} or s.startswith("<"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_daily_period(period: str) -> date | None:
    """`daily-region-data` periods are YYYY-MM-DD."""
    if not isinstance(period, str):
        return None
    parts = period.split("-")
    if len(parts) != 3:
        return None
    try:
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError):
        return None


def _year_month(d: date) -> str:
    """Key for monthly aggregation."""
    return f"{d.year:04d}-{d.month:02d}"


def _first_of_month(d: date) -> date:
    return d.replace(day=1)


def _latest_capacity_month(today: date) -> str:
    """Nameplate capacity lags ~3 months; walk back to a reliably complete month."""
    year, month = today.year, today.month
    month -= 3
    while month <= 0:
        month += 12
        year -= 1
    return f"{year:04d}-{month:02d}"


class EIAISORTOAdapter(Adapter):
    """EIA ISO/RTO daily grid operations + per-region capacity."""

    name = "eia_isorto"
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
    def _get_json(self, client: httpx.Client, url: str, params: dict[str, Any]) -> dict[str, Any]:
        """GET a single EIA v2 request, with retry on transient errors."""
        resp = client.get(url, params=params)
        if resp.status_code == 429 or resp.status_code >= 500:
            resp.raise_for_status()
        if resp.status_code >= 400:
            raise _EIAISORTOHardError(f"EIA ISO/RTO {url} returned {resp.status_code}: {resp.text[:200]}")
        return resp.json()  # type: ignore[no-any-return]

    def _fetch_region_data(
        self,
        client: httpx.Client,
        period_start: date,
        period_end: date,
    ) -> list[dict[str, Any]]:
        """Fetch all daily rows for demand (D) and net generation (NG)."""
        regions = _configured_regions(self._settings)
        if not regions:
            return []

        base_url = f"{self._settings.eia_base_url}/electricity/rto/daily-region-data/data/"
        params: dict[str, Any] = {
            "api_key": self._settings.eia_api_key or "",
            "frequency": "daily",
            "data[0]": "value",
            "facets[type][]": ["D", "NG"],
            "facets[respondent][]": list(regions),
            "start": period_start.isoformat(),
            "end": period_end.isoformat(),
            "sort[0][column]": "period",
            "sort[0][direction]": "asc",
            "length": _PAGE_SIZE,
        }

        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            params["offset"] = offset
            body = self._get_json(client, base_url, params)
            page = body.get("response", {}).get("data", [])
            if not page:
                break
            rows.extend(page)
            if len(page) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE
        return rows

    def _aggregate_region_data(
        self,
        rows: list[dict[str, Any]],
    ) -> dict[tuple[str, str, str], Any]:
        """Group daily rows into monthly peaks (D) and totals (NG).

        Returns {(region, year_month, signal_name): value}.
        """
        buckets: dict[tuple[str, str, str], list[float]] = defaultdict(list)
        for row in rows:
            region = row.get("respondent") or row.get("respondent-id") or row.get("respondent_id")
            row_type = row.get("type") or row.get("type-name") or row.get("type-description")
            period_raw = row.get("period", "")
            period = _parse_daily_period(str(period_raw))
            value = _coerce_value(row.get("value"))
            if region is None or row_type is None or period is None or value is None:
                continue

            key_month = _year_month(period)
            if row_type in ("D", "Demand"):
                buckets[(region, key_month, "iso_peak_load_mw")].append(value)
            elif row_type in ("NG", "Net generation"):
                buckets[(region, key_month, "iso_net_generation_mwh")].append(value)

        out: dict[tuple[str, str, str], Any] = {}
        for (region, key_month, signal_name), values in buckets.items():
            if signal_name == "iso_peak_load_mw":
                out[(region, key_month, signal_name)] = max(values)
            else:
                out[(region, key_month, signal_name)] = sum(values)
        return out

    def _emit_region_signals(
        self,
        aggregates: dict[tuple[str, str, str], Any],
    ) -> list[RawSignal]:
        """Turn monthly aggregates into RawSignals per mapped segment."""
        signals: list[RawSignal] = []
        for (region, key_month, signal_name), value in aggregates.items():
            year = int(key_month[:4])
            month = int(key_month[5:])
            try:
                observed_at = date(year, month, 1)
            except ValueError:
                continue
            unit = "MW" if signal_name == "iso_peak_load_mw" else "MWh"
            for segment in _region_segments(region, self._settings):
                try:
                    signals.append(
                        RawSignal(
                            segment=segment,
                            subsegment=f"iso:{region}",
                            signal_name=signal_name,
                            value_num=value,
                            value_text=str(value),
                            unit=unit,
                            geography=region,
                            source=self.name,
                            source_id=f"{self.name}:{region}:{signal_name}:{key_month}",
                            observed_at=observed_at,
                        )
                    )
                except ValidationError:
                    _LOGGER.debug("dropped malformed ISO/RTO row for %s %s", region, signal_name)
        return signals

    def _fetch_state_capacity(
        self,
        client: httpx.Client,
        state: str,
        period: str,
    ) -> tuple[str, float] | None:
        """Sum operating nameplate capacity for one state in the latest month."""
        url = f"{self._settings.eia_base_url}/electricity/operating-generator-capacity/data/"
        params: dict[str, Any] = {
            "api_key": self._settings.eia_api_key or "",
            "frequency": "monthly",
            "data[0]": "nameplate-capacity-mw",
            "facets[stateid][]": state,
            "facets[status][]": "OP",
            "start": period,
            "end": period,
            "length": _PAGE_SIZE,
        }
        try:
            body = self._get_json(client, url, params)
        except _EIAISORTOHardError as e:
            _LOGGER.warning("EIA ISO/RTO capacity %s: %s", state, e)
            return None

        rows = body.get("response", {}).get("data", [])
        total = 0.0
        for row in rows:
            v = _coerce_value(row.get("nameplate-capacity-mw"))
            if v is not None:
                total += v
        return state, total

    def _fetch_capacity_by_region(
        self,
        client: httpx.Client,
    ) -> dict[str, float]:
        """Aggregate per-state operating capacity to enabled regions."""
        regions = _configured_regions(self._settings)
        states = _states_for_regions(regions)
        latest = _latest_capacity_month(date.today())

        state_totals: dict[str, float] = {}
        for state in states:
            result = self._fetch_state_capacity(client, state, latest)
            if result is None:
                continue
            _, total = result
            state_totals[state] = total

        region_capacity: dict[str, float] = {}
        for region in regions:
            cap = sum(state_totals.get(s, 0.0) for s in _REGION_TO_STATES[region])
            if cap > 0:
                region_capacity[region] = cap
        return region_capacity

    def _emit_capacity_signals(
        self,
        region_capacity: dict[str, float],
    ) -> list[RawSignal]:
        """Emit one `iso_capacity_mw` signal per region per segment."""
        latest = _latest_capacity_month(date.today())
        observed_at = date.fromisoformat(f"{latest}-01")
        signals: list[RawSignal] = []
        for region, cap in region_capacity.items():
            for segment in _region_segments(region, self._settings):
                try:
                    signals.append(
                        RawSignal(
                            segment=segment,
                            subsegment=f"iso:{region}",
                            signal_name="iso_capacity_mw",
                            value_num=cap,
                            value_text=str(cap),
                            unit="MW",
                            geography=region,
                            source=self.name,
                            source_id=f"{self.name}:{region}:capacity:{latest}",
                            observed_at=observed_at,
                        )
                    )
                except ValidationError:
                    _LOGGER.debug("dropped malformed capacity row for %s", region)
        return signals

    def fetch(
        self,
        period_start: date,
        period_end: date,
        progress: ProgressCallback | None = None,
    ) -> list[RawSignal]:
        ok, reason = self.is_configured()
        if not ok:
            _LOGGER.info("EIA ISO/RTO: %s; skipping fetch", reason)
            return []

        # Monthly-cadence window from the orchestrator is too narrow for
        # the 13-month YoY view the normalizer may want; widen to 2 years.
        if (period_end - period_start).days < 365:
            period_start = period_end.replace(year=period_end.year - 2)

        signals: list[RawSignal] = []
        with httpx.Client(timeout=self._settings.eia_timeout_s) as client:
            region_rows = self._fetch_region_data(client, period_start, period_end)
            aggregates = self._aggregate_region_data(region_rows)
            signals.extend(self._emit_region_signals(aggregates))

            region_capacity = self._fetch_capacity_by_region(client)
            signals.extend(self._emit_capacity_signals(region_capacity))

        return signals


def build_eia_isorto_adapter(settings: Settings) -> EIAISORTOAdapter:
    """Factory used by the ingest registry."""
    return EIAISORTOAdapter(settings)
