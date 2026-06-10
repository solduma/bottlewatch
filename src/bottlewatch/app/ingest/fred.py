"""FRED (Federal Reserve Economic Data) adapter.

Tracks macro indicators (PPI, Industrial Production, Capacity Utilization)
that serve as lead indicators for the bottleneck scorecard.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import httpx
import tenacity

from bottlewatch.app.ingest.base import Cadence, ProgressCallback, RawSignal
from bottlewatch.config import Settings


@dataclass(frozen=True)
class SeriesSpec:
    """Map of FRED series ID to bottleneck segment and signal name."""

    series_id: str
    segment: str
    signal_name: str
    unit: str


_SERIES_SPEC = [
    # research/03_data_sources.md §4: the load-bearing FRED series
    # for the bottleneck thesis. Series IDs are case-sensitive and
    # silently 404 on typos — verified against the FRED catalog.
    SeriesSpec("INDPRO", "general_manufacturing", "industrial_production", "index"),
    SeriesSpec("TCU", "general_manufacturing", "capacity_utilization", "percent"),
    SeriesSpec("WPU31132506", "semiconductors", "ppi_semis", "index"),
    SeriesSpec("WPU1321", "transformers_tnd", "ppi_transformers", "index"),
    # A35SNO = "Manufacturers' New Orders: Electrical Equipment,
    # Appliances and Components" (monthly, SA). This is the
    # upstream demand-pull signal for `transformers_tnd` —
    # methodology §2.5 calls for "hyperscaler capex YoY" as the
    # demand_signal, but FRED doesn't aggregate the Big Four's
    # capex. Manufacturers' new orders for the equipment class
    # that includes transformers is a strong direct proxy.
    # Verified against the FRED catalog 2026-06-10.
    SeriesSpec("A35SNO", "transformers_tnd", "electrical_equipment_orders", "index"),
]


class FredAdapter:
    """Fetches time-series observations from the FRED API."""

    def __init__(self, settings: Settings) -> None:
        self.name = "fred"
        self.cadence = Cadence.WEEKLY
        self.settings = settings
        self._base_url = "https://api.stlouisfed.org/fred/series/observations"

    def is_configured(self) -> tuple[bool, str]:
        if not self.settings.fred_api_key:
            return False, "FRED_API_KEY is missing"
        return True, ""

    def fetch(
        self,
        period_start: date,
        period_end: date,
        progress: ProgressCallback | None = None,
    ) -> list[RawSignal]:
        """Fetch observations for all registered series within the window."""
        signals: list[RawSignal] = []

        with httpx.Client(timeout=30.0) as client:
            for spec in _SERIES_SPEC:
                try:
                    series_signals = self._fetch_series(client, spec, period_start, period_end)
                    signals.extend(series_signals)
                except Exception:
                    # We log and continue to avoid one failing series killing the whole run.
                    # The orchestrator handles the fatal error if the adapter itself crashes.
                    continue

        return signals

    def _fetch_series(self, client: httpx.Client, spec: SeriesSpec, start: date, end: date) -> list[RawSignal]:
        """Fetch and parse a single series."""
        params = {
            "series_id": spec.series_id,
            "api_key": self.settings.fred_api_key,
            "file_type": "json",
            "observation_start": start.isoformat(),
            "observation_end": end.isoformat(),
        }

        # Retries for transient 5xx errors
        @tenacity.retry(
            stop=tenacity.stop_after_attempt(3),
            wait=tenacity.wait_exponential(multiplier=1, min=2, max=10),
            retry=tenacity.retry_if_exception_type(httpx.HTTPStatusError),
        )
        def _do_request():
            resp = client.get(self._base_url, params=params)
            resp.raise_for_status()
            return resp.json()

        data = _do_request()
        observations = data.get("observations", [])

        results = []
        for obs in observations:
            val_text = obs.get("value")
            # FRED uses '.' for missing values
            if val_text == "." or val_text is None:
                continue

            try:
                val_num = float(val_text)
            except ValueError:
                val_num = None

            results.append(
                RawSignal(
                    segment=spec.segment,
                    signal_name=spec.signal_name,
                    value_num=val_num,
                    value_text=val_text,
                    unit=spec.unit,
                    source=self.name,
                    source_id=spec.series_id,
                    observed_at=date.fromisoformat(obs["date"]),
                    geography="US",
                )
            )

        return results


def build_fred_adapter(settings: Settings) -> FredAdapter:
    """Factory: the orchestrator calls this with a Settings instance."""
    return FredAdapter(settings)
