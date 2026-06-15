"""Loader for the manual hyperscaler AI capex ledger.

The ledger lives at `research/06_capacity_ledger.json` and is edited
by hand after each quarterly earnings cycle. It provides the primary
demand_signal for AI-supply-chain segments until an automated EDGAR
extractor lands in a later phase.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import NotRequired, TypedDict

_PROJECT_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_LEDGER_PATH = _PROJECT_ROOT / "research" / "06_capacity_ledger.json"


class LedgerEntry(TypedDict):
    ticker: str
    fiscal_quarter: str
    ai_capex_usd_b: float
    source: str
    url: NotRequired[str | None]
    updated_by: NotRequired[str | None]


class LedgerSegment(TypedDict):
    signal_name: str
    unit: str
    entries: NotRequired[list[LedgerEntry]]
    entries_ref: NotRequired[str]


Ledger = dict[str, LedgerSegment]


@dataclass(frozen=True)
class CapexSeries:
    """A normalized series of total AI capex by fiscal quarter."""

    quarters: list[str]
    values: list[float]
    unit: str
    source_count: int  # number of distinct tickers contributing


@lru_cache(maxsize=1)
def _load_ledger_from(path: str) -> Ledger:
    with Path(path).open() as f:
        raw: Ledger = json.load(f)
    # Drop the underscore-prefixed comment key if present.
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def load_ledger(path: Path | None = None) -> Ledger:
    """Return the parsed capex ledger. Cached at module level."""
    return _load_ledger_from(str(path or _DEFAULT_LEDGER_PATH))


def _resolve_entries(segment: str, ledger: Ledger) -> list[LedgerEntry]:
    """Return entries for a segment, following `entries_ref` links."""
    spec = ledger.get(segment)
    if spec is None:
        return []
    entries = spec.get("entries")
    if entries is not None:
        return entries
    ref = spec.get("entries_ref")
    if ref:
        return _resolve_entries(ref, ledger)
    return []


def series_for_segment(segment: str, ledger: Ledger | None = None) -> CapexSeries | None:
    """Build an aggregate AI capex series for `segment`.

    Sums `ai_capex_usd_b` across tickers per fiscal quarter and returns
    the sorted quarter list plus totals. Returns None if the segment
    has no ledger entries.
    """
    ledger = ledger if ledger is not None else load_ledger()
    entries = _resolve_entries(segment, ledger)
    if not entries:
        return None

    by_quarter: dict[str, float] = {}
    tickers: set[str] = set()
    for e in entries:
        q = e["fiscal_quarter"]
        by_quarter[q] = by_quarter.get(q, 0.0) + e["ai_capex_usd_b"]
        tickers.add(e["ticker"])

    quarters = sorted(by_quarter.keys())
    values = [by_quarter[q] for q in quarters]
    return CapexSeries(
        quarters=quarters,
        values=values,
        unit="USD_B",
        source_count=len(tickers),
    )


def latest_quarter(series: CapexSeries) -> tuple[str, float] | None:
    """Return the most recent (quarter, value) pair, or None."""
    if not series.quarters:
        return None
    return series.quarters[-1], series.values[-1]
