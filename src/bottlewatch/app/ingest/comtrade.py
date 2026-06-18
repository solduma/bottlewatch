"""UN Comtrade adapter.

Tracks global trade flows for critical bottleneck commodities (HBM, lithography, transformers)
using Harmonized System (HS) codes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import httpx
import tenacity

from bottlewatch.app.ingest.base import Cadence, ProgressCallback, RawSignal
from bottlewatch.config import Settings

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommoditySpec:
    """Map of HS code to bottleneck segment and signal name."""

    hs_code: str
    segment: str
    signal_name: str
    unit: str


# HS codes mapped to canonical scoring segment slugs so downstream
# extractors can consume them without a second translation layer.
_COMMODITY_SPEC = [
    CommoditySpec("8541", "hbm_memory", "trade_volume", "USD"),
    CommoditySpec("8542", "hbm_memory", "trade_volume", "USD"),
    CommoditySpec("8486", "advanced_packaging", "trade_volume", "USD"),
    CommoditySpec("8504", "transformers_tnd", "trade_volume", "USD"),
]


class ComtradeAdapter:
    """Fetches trade data from the UN Comtrade API."""

    def __init__(self, settings: Settings) -> None:
        self.name = "comtrade"
        self.cadence = Cadence.MONTHLY
        self.settings = settings
        self._base_url = "https://comtradeapi.un.org/api/get"

    def is_configured(self) -> tuple[bool, str]:
        if not self.settings.comtrade_api_key:
            return False, "COMTRADE_API_KEY is missing"
        return True, ""

    def fetch(
        self,
        period_start: date,
        period_end: date,
        progress: ProgressCallback | None = None,
    ) -> list[RawSignal]:
        """Fetch trade volumes for registered commodities within the window."""
        signals: list[RawSignal] = []

        with httpx.Client(timeout=30.0) as client:
            for spec in _COMMODITY_SPEC:
                try:
                    commodity_signals = self._fetch_commodity(client, spec, period_start, period_end)
                    signals.extend(commodity_signals)
                except Exception as e:
                    # Log and continue: one bad HS code shouldn't kill the run,
                    # but the failure must be visible so a degraded fetch isn't
                    # reported as a clean OK-with-zero-rows.
                    _LOGGER.warning("Comtrade HS code %s failed: %s", spec.hs_code, e)
                    continue

        return signals

    def _fetch_commodity(self, client: httpx.Client, spec: CommoditySpec, start: date, end: date) -> list[RawSignal]:
        """Fetch trade data for a specific HS code."""
        params = {
            "subscriptionKey": self.settings.comtrade_api_key,
            "startPeriod": start.year,
            "endPeriod": end.year,
            "reporterCode": "840",  # USA
            "cmdCode": spec.hs_code,
            "flow": "M",  # Import
            "freq": "M",  # Monthly
        }

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
        observations = data.get("data", [])

        results = []
        for obs in observations:
            # Expected fields: period, tradeValue
            period_raw = obs.get("period")
            val_text = obs.get("tradeValue")

            if not period_raw or val_text is None:
                continue

            try:
                # Comtrade periods are often just years (YYYY) or months (YYYY-MM).
                # Normalize to a date object.
                p_str = str(period_raw)
                if len(p_str) == 4:  # YYYY
                    observed_at = date(int(p_str), 1, 1)
                elif len(p_str) == 7:  # YYYY-MM
                    observed_at = date(int(p_str[:4]), int(p_str[5:]), 1)
                else:
                    observed_at = date.fromisoformat(p_str)
                val_num = float(val_text)
            except (ValueError, TypeError):
                continue

            results.append(
                RawSignal(
                    segment=spec.segment,
                    signal_name=spec.signal_name,
                    value_num=val_num,
                    value_text=val_text,
                    unit=spec.unit,
                    source=self.name,
                    source_id=f"{spec.hs_code}_{period_raw}",
                    observed_at=observed_at,
                    geography="US",
                )
            )

        return results


def build_comtrade_adapter(settings: Settings) -> ComtradeAdapter:
    """Factory: the orchestrator calls this with a Settings instance."""
    return ComtradeAdapter(settings)
