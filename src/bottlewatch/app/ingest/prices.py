"""Ingest adapter for daily equity prices used by the walk-forward backtest.

Spec:
- Inputs: research/02_universe.csv (ticker column); Settings fields
  price_data_source ("csv" | "yfinance" | "alphavantage") and price_api_key.
- Outputs: data/processed/prices.csv with columns ticker,date,close.
  Fetched rows merge into the existing file, preserving rows not overwritten.
- Behavior: source="csv" is a no-op (CSV fallback). yfinance fetches adjusted
  close per ticker. Alpha Vantage requires PRICE_API_KEY and fetches daily
  adjusted close. Out-of-window dates are filtered.
- Errors: missing universe raises FileNotFoundError; unsupported source
  raises ValueError; per-ticker failures log a warning and continue.
- Out of scope: real-time intraday data, FX conversion, dividend/split
  logic beyond what the source returns, DB writes.
- Testable properties: mocked yfinance/AV payloads parse into PriceBar;
  merge preserves old rows and overwrites duplicate (ticker,date); csv
  source leaves prices.csv unchanged; CsvPriceProvider reads the output.
"""

from __future__ import annotations

import csv
import logging
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx
import yfinance as yf

from bottlewatch.app.backtest.prices import PriceBar
from bottlewatch.app.ingest.base import ProgressCallback
from bottlewatch.config import Settings

_LOGGER = logging.getLogger(__name__)

# Alpha Vantage free tier is 5 calls per minute and 25 calls per day.
# Sleeping 12s between tickers keeps us under the per-minute limit.
_ALPHAVANTAGE_RATE_LIMIT_S = 12


def _read_universe_tickers(path: Path) -> list[str]:
    """Return unique tickers from the universe CSV."""
    if not path.exists():
        raise FileNotFoundError(f"Universe CSV not found: {path}")
    tickers: list[str] = []
    seen: set[str] = set()
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            ticker = (row.get("ticker") or "").strip()
            if ticker and ticker not in seen:
                seen.add(ticker)
                tickers.append(ticker)
    return tickers


def _filter_by_date(bars: list[PriceBar], start: date, end: date) -> list[PriceBar]:
    return [b for b in bars if start <= b.date <= end]


def _parse_yfinance_history(ticker: str, df: Any) -> list[PriceBar]:
    """Convert a yfinance DataFrame to PriceBar objects."""
    if df is None or df.empty:
        return []
    close_col: str | None = None
    for candidate in ("Adj Close", "Close"):
        if candidate in df.columns:
            close_col = candidate
            break
    if close_col is None:
        _LOGGER.warning("No close column found in yfinance history for %s", ticker)
        return []

    bars: list[PriceBar] = []
    for ts, row in df.iterrows():
        try:
            close = float(row[close_col])
        except (TypeError, ValueError):
            continue
        d = ts.date() if hasattr(ts, "date") else date.fromisoformat(str(ts)[:10])
        bars.append(PriceBar(ticker=ticker, date=d, close=close))
    return bars


def fetch_prices_yfinance(
    tickers: list[str],
    start: date,
    end: date,
    progress: ProgressCallback | None = None,
) -> list[PriceBar]:
    """Fetch adjusted close prices from Yahoo Finance via yfinance."""
    bars: list[PriceBar] = []
    # yfinance's end date is exclusive; add one day to include `end`.
    yf_end = end + timedelta(days=1)
    for i, ticker in enumerate(tickers):
        if progress:
            progress(i, len(tickers), ticker)
        try:
            ticker_obj: Any = yf.Ticker(ticker)
            df: Any = ticker_obj.history(start=start.isoformat(), end=yf_end.isoformat())
            bars.extend(_filter_by_date(_parse_yfinance_history(ticker, df), start, end))
        except Exception:  # noqa: BLE001 - per-ticker failure should not kill the run
            _LOGGER.warning("Failed to fetch prices for %s from yfinance", ticker)
        # Be polite to Yahoo's servers.
        time.sleep(0.2)
    if progress:
        progress(len(tickers), len(tickers), "")
    return bars


def _parse_alphavantage_series(
    ticker: str,
    payload: dict[str, Any],
    start: date,
    end: date,
) -> list[PriceBar]:
    """Parse Alpha Vantage TIME_SERIES_DAILY_ADJUSTED JSON into PriceBars."""
    series = payload.get("Time Series (Daily)")
    if not isinstance(series, dict):
        return []
    bars: list[PriceBar] = []
    for d_str, values in series.items():
        d: date
        try:
            d = date.fromisoformat(d_str)
        except ValueError:
            continue
        if not (start <= d <= end):
            continue
        close_raw = values.get("5. adjusted close") if isinstance(values, dict) else None
        if close_raw is None:
            continue
        try:
            close = float(close_raw)
        except (TypeError, ValueError):
            continue
        bars.append(PriceBar(ticker=ticker, date=d, close=close))
    return bars


def fetch_prices_alphavantage(
    tickers: list[str],
    api_key: str,
    start: date,
    end: date,
    progress: ProgressCallback | None = None,
) -> list[PriceBar]:
    """Fetch adjusted close prices from Alpha Vantage."""
    bars: list[PriceBar] = []
    base_url = "https://www.alphavantage.co/query"
    params = {
        "function": "TIME_SERIES_DAILY_ADJUSTED",
        "outputsize": "full",
        "datatype": "json",
        "apikey": api_key,
    }
    with httpx.Client(timeout=30.0) as client:
        for i, ticker in enumerate(tickers):
            if progress:
                progress(i, len(tickers), ticker)
            try:
                resp = client.get(base_url, params={**params, "symbol": ticker})
                resp.raise_for_status()
                payload = resp.json()
                bars.extend(_parse_alphavantage_series(ticker, payload, start, end))
            except Exception:  # noqa: BLE001
                _LOGGER.warning("Failed to fetch prices for %s from Alpha Vantage", ticker)
            # Respect Alpha Vantage's free-tier rate limit.
            if i < len(tickers) - 1:
                time.sleep(_ALPHAVANTAGE_RATE_LIMIT_S)
    if progress:
        progress(len(tickers), len(tickers), "")
    return bars


def fetch_prices(
    source: str,
    tickers: list[str],
    start: date,
    end: date,
    api_key: str | None = None,
    progress: ProgressCallback | None = None,
) -> list[PriceBar]:
    """Dispatch to the requested price source."""
    if source == "csv":
        return []
    if source == "yfinance":
        return fetch_prices_yfinance(tickers, start, end, progress=progress)
    if source == "alphavantage":
        if not api_key:
            raise ValueError("Alpha Vantage price source requires PRICE_API_KEY")
        return fetch_prices_alphavantage(tickers, api_key, start, end, progress=progress)
    raise ValueError(f"Unsupported price_data_source: {source}")


def _load_price_csv(path: Path) -> dict[tuple[str, date], PriceBar]:
    """Load an existing prices.csv into a lookup keyed by (ticker, date)."""
    if not path.exists():
        return {}
    out: dict[tuple[str, date], PriceBar] = {}
    with path.open(newline="", encoding="utf-8") as fh:
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
            out[(ticker, d)] = PriceBar(ticker=ticker, date=d, close=c)
    return out


def merge_prices_csv(bars: list[PriceBar], path: Path) -> int:
    """Merge bars into path, overwriting existing (ticker,date) rows.

    Returns the number of rows written.
    """
    existing = _load_price_csv(path)
    for bar in bars:
        existing[(bar.ticker, bar.date)] = bar
    rows = sorted(existing.values(), key=lambda b: (b.ticker, b.date))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["ticker", "date", "close"])
        for row in rows:
            writer.writerow([row.ticker, row.date.isoformat(), f"{row.close:.4f}"])
    return len(rows)


def run_refresh_prices(
    *,
    settings: Settings,
    universe_path: Path,
    output_path: Path,
    source: str | None = None,
    start: date | None = None,
    end: date | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Refresh prices.csv from the configured source.

    Returns a summary dict with tickers, source, rows_written, and path.
    """
    source = source or settings.price_data_source
    if source == "csv":
        return {
            "source": "csv",
            "tickers": 0,
            "rows_written": 0,
            "path": str(output_path),
            "detail": "source is csv; no fetch performed",
        }

    tickers = _read_universe_tickers(universe_path)
    if not tickers:
        return {
            "source": source,
            "tickers": 0,
            "rows_written": 0,
            "path": str(output_path),
            "detail": "no tickers found in universe",
        }

    today = date.today()
    end = end or today
    start = start or (end - timedelta(days=settings.price_lookback_days))

    bars = fetch_prices(
        source=source,
        tickers=tickers,
        start=start,
        end=end,
        api_key=settings.price_api_key,
        progress=progress,
    )
    rows_written = merge_prices_csv(bars, output_path)
    return {
        "source": source,
        "tickers": len(tickers),
        "rows_written": rows_written,
        "path": str(output_path),
        "detail": "",
    }
