"""Price providers for the walk-forward backtest.

The backtest job needs daily close prices for the universe of
tickers. We deliberately ship only a CSV provider: pulling live
prices for 200+ tickers across NYSE/NASDAQ/TWSE/KRX/SZSE/TSE
would require a yfinance-style adapter, FX handling, and holiday
normalization. The CSV keeps the backtest reproducible and
offline.

`prices.csv` is expected at `data/processed/prices.csv` with
columns `ticker,date,close` (one row per ticker per trading day).
The user is expected to populate this file from their preferred
price source (yfinance, broker API, vendor feed, etc.).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class PriceBar:
    """One daily close price for one ticker."""

    ticker: str
    date: date
    close: float


class PriceProvider(Protocol):
    """The contract the backtest job relies on."""

    def get_prices(self, ticker: str, start: date, end: date) -> list[PriceBar]: ...


class CsvPriceProvider:
    """Read prices from a CSV file at `path`.

    The file is loaded once and indexed in-memory by ticker. For
    a 200-ticker universe with ~5 years of daily bars, this is
    ~250k rows — well under 100MB and trivially fast to scan.

    Missing file: returns empty results. Unknown ticker: returns
    empty. Out-of-window bar: filtered out.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._by_ticker: dict[str, list[PriceBar]] | None = None

    def _load(self) -> dict[str, list[PriceBar]]:
        if self._by_ticker is not None:
            return self._by_ticker
        out: dict[str, list[PriceBar]] = {}
        if not self._path.exists():
            self._by_ticker = out
            return out
        with self._path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                ticker = (row.get("ticker") or "").strip()
                d_raw = (row.get("date") or "").strip()
                c_raw = (row.get("close") or "").strip()
                if not ticker or not d_raw or not c_raw:
                    continue
                try:
                    d = date.fromisoformat(d_raw)
                    c = float(c_raw)
                except ValueError:
                    continue
                out.setdefault(ticker, []).append(PriceBar(ticker, d, c))
        # Sort each ticker's bars ascending by date so the consumer
        # can use bisect or simple slicing.
        for bars in out.values():
            bars.sort(key=lambda b: b.date)
        self._by_ticker = out
        return out

    def get_prices(self, ticker: str, start: date, end: date) -> list[PriceBar]:
        """Return bars for `ticker` whose date is in [start, end], sorted by date."""
        all_bars = self._load().get(ticker, [])
        return [b for b in all_bars if start <= b.date <= end]
