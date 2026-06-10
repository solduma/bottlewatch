"""EIA Open Data v2 capacity aggregator.

The EIA v2 `operating-generator-capacity` route (Forms EIA-860/860M)
exposes per-generator nameplate capacity, not a US-total aggregate.
This adapter fetches the latest-month, operating-only rows for each
US state (the facet list does not include a 'US' rollup), sums the
`nameplate-capacity-mw` per state, and emits one signal per state plus
a US total. The US total is the sum of state totals; we do NOT call
the API twice for it.

For v1.1, M3, this can be replaced with a direct `/electricity/state-
electricity-profiles/` rollup when (or if) that route exposes capacity.
For M1.1, the per-state fetch is the simplest path that does not rely
on hidden aggregation logic.

The adapter is structured like the rest of the EIA adapter (httpx +
tenacity + same retry semantics) but it lives in its own module
because the request shape is facets-based rather than the v1-bridge
`/seriesid/` ID. Reusing `_get_json` would muddle the contract.
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

from bottlewatch.app.config_loader import load_eia_states
from bottlewatch.app.ingest.base import Adapter, Cadence, ProgressCallback, RawSignal
from bottlewatch.config import Settings

_LOGGER = logging.getLogger(__name__)

# Transient conditions that warrant a retry. Mirrors eia.py.
_RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    httpx.TransportError,
    httpx.HTTPStatusError,
)


class _EIAHardError(Exception):
    """Raised for non-retryable 4xx responses (bad facet, bad key, ...)."""


# The 50 states + DC. Source: facet/stateid/ on the v2 API. We
# hard-code the list rather than calling the facet endpoint so a single
# network blip on the first request does not break the whole run.
# The list lives in research/config/eia_states.json so it can be
# edited without a code change.
_STATES: tuple[str, ...] = load_eia_states()

_PAGE_SIZE = 5000  # EIA v2 cap; see plan §9.


def _coerce_float(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _latest_month_window(today: date) -> tuple[str, str]:
    """Return a (start, end) string pair in YYYY-MM covering the latest
    month EIA actually has data for. Observed on 2026-06-03: the latest
    period with rows is 2026-03, so we walk back three months.
    """
    year, month = today.year, today.month
    # Three-month lag: month-2 (e.g. 2026-04) is sometimes partial;
    # month-3 (2026-03) is reliably complete.
    month -= 3
    while month <= 0:
        month += 12
        year -= 1
    return f"{year:04d}-{month:02d}", f"{year:04d}-{month:02d}"


class EIAV2CapacityAdapter(Adapter):
    """Aggregator over `operating-generator-capacity` → state & US totals."""

    name = "eia_v2_capacity"
    cadence = Cadence.WEEKLY  # Generator inventory churns on a slower cycle than gen.

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
    def _get_state_rows(self, client: httpx.Client, state: str, period: str) -> list[dict[str, Any]]:
        """Fetch the latest-month operating generators for one state."""
        url = f"{self._settings.eia_base_url}/electricity/operating-generator-capacity/data/"
        params: dict[str, str | int] = {
            "api_key": self._settings.eia_api_key or "",
            "frequency": "monthly",
            "data[0]": "nameplate-capacity-mw",
            "facets[stateid][]": state,
            "facets[status][]": "OP",
            "start": period,
            "end": period,
            "sort[0][column]": "nameplate-capacity-mw",
            "sort[0][direction]": "desc",
            "length": _PAGE_SIZE,
        }
        resp = client.get(url, params=params)
        if resp.status_code == 429 or resp.status_code >= 500:
            resp.raise_for_status()
        if resp.status_code >= 400:
            raise _EIAHardError(f"EIA v2 capacity {state} returned {resp.status_code}: {resp.text[:200]}")
        body = resp.json()
        return body.get("response", {}).get("data", [])  # type: ignore[no-any-return]

    def _fetch_state_total(self, client: httpx.Client, state: str, period: str) -> tuple[str, float] | None:
        """Sum one state's operating capacity for the latest month.

        Returns None if the API call hard-errors (caller decides whether
        to skip the state or surface ERROR). For a "soft" empty state
        (no rows), returns (state, 0.0).
        """
        rows = self._get_state_rows(client, state, period)
        if not rows:
            return state, 0.0
        total = 0.0
        for r in rows:
            v = _coerce_float(r.get("nameplate-capacity-mw"))
            if v is not None:
                total += v
        return state, total

    def fetch(
        self,
        period_start: date,
        period_end: date,
        progress: ProgressCallback | None = None,
    ) -> list[RawSignal]:
        ok, reason = self.is_configured()
        if not ok:
            _LOGGER.info("EIA v2 capacity: %s; skipping fetch", reason)
            return []
        del period_start, period_end  # window is "latest month", not the orchestrator's range

        _, latest = _latest_month_window(date.today())
        signals: list[RawSignal] = []
        state_totals: dict[str, float] = {}
        with httpx.Client(timeout=self._settings.eia_timeout_s) as client:
            for state in _STATES:
                try:
                    result = self._fetch_state_total(client, state, latest)
                except _EIAHardError as e:
                    # Hard error on a single state: skip it and keep going.
                    # If every state hard-errors, the orchestrator will see
                    # the propagated exception from a later surface (we
                    # re-raise at the end if zero states succeeded).
                    _LOGGER.warning("EIA v2 capacity %s: %s", state, e)
                    continue
                if result is None:
                    continue
                s, total = result
                state_totals[s] = total
                try:
                    signals.append(
                        RawSignal(
                            segment="power_generation_oem",
                            signal_name="capacity_mw",
                            value_num=total,
                            unit="MW",
                            geography=f"US-{s}",
                            source=self.name,
                            source_id=f"operating-generator-capacity:{s}:{latest}",
                            observed_at=date.fromisoformat(f"{latest}-01"),
                        )
                    )
                except ValidationError:
                    _LOGGER.debug("dropped malformed row for state %s", s)

        if not state_totals:
            # Every state hard-errored or returned nothing. Surface as
            # a hard error so the orchestrator records ERROR.
            raise _EIAHardError("no state returned rows; capacity fetch is unhealthy")

        us_total = sum(state_totals.values())
        try:
            signals.append(
                RawSignal(
                    segment="power_generation_oem",
                    signal_name="capacity_mw",
                    value_num=us_total,
                    unit="MW",
                    geography="US",
                    source=self.name,
                    source_id=f"operating-generator-capacity:US:{latest}",
                    observed_at=date.fromisoformat(f"{latest}-01"),
                )
            )
        except ValidationError:
            _LOGGER.debug("dropped US-total row")

        return signals


def build_eia_v2_capacity_adapter(settings: Settings) -> EIAV2CapacityAdapter:
    """Factory: the orchestrator calls this with a Settings instance."""
    return EIAV2CapacityAdapter(settings)
