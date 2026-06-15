"""Tests for the live equity price ingest adapter and refresh job."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
import respx
from httpx import Response

from bottlewatch.app.backtest.prices import CsvPriceProvider, PriceBar
from bottlewatch.app.ingest.prices import (
    fetch_prices,
    fetch_prices_alphavantage,
    fetch_prices_yfinance,
    merge_prices_csv,
    run_refresh_prices,
)
from bottlewatch.config import Settings


def _universe_csv(tmp_path: Path) -> Path:
    p = tmp_path / "universe.csv"
    p.write_text(
        "ticker,exchange,name,segment,subsegment,exposure_pct,market_cap_bucket,mcap_usd,currency_hedge,notes\n"
        "AAA,NASDAQ,AAA,seg_a,sub_a,80,large,1000000000,USD,note\n"
        "BBB,NASDAQ,BBB,seg_b,sub_b,80,large,1000000000,USD,note\n"
    )
    return p


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def test_settings_price_defaults(tmp_path: Path) -> None:
    settings = Settings(
        database_url="sqlite:///:memory:",
        refresh_log_path=tmp_path / "refresh.log",
    )
    assert settings.price_data_source == "csv"
    assert settings.price_api_key is None
    assert settings.prices_csv_path.name == "prices.csv"
    assert settings.price_lookback_days == 730


def test_settings_price_source_override(tmp_path: Path) -> None:
    settings = Settings(
        price_data_source="yfinance",
        price_api_key="secret",
        database_url="sqlite:///:memory:",
        refresh_log_path=tmp_path / "refresh.log",
    )
    assert settings.price_data_source == "yfinance"
    assert settings.price_api_key == "secret"


# ---------------------------------------------------------------------------
# yfinance fetcher
# ---------------------------------------------------------------------------


def _make_history(ticker: str, rows: list[tuple[date, float]]) -> Any:
    """Build a minimal pandas DataFrame that mimics yfinance output."""
    import pandas as pd

    index = pd.DatetimeIndex([d for d, _ in rows])
    data = {"Close": [c for _, c in rows]}
    df = pd.DataFrame(data, index=index)
    df.attrs["ticker"] = ticker
    return df


class _FakeTicker:
    def __init__(self, histories: dict[str, Any]) -> None:
        self._histories = histories

    def history(self, *, start: str, end: str) -> Any:
        # start/end are ignored by the fake; return the pre-canned frame.
        return self._histories.get(self.ticker, None)  # type: ignore[attr-defined]


def test_yfinance_fetcher_parses_close(monkeypatch: Any, tmp_path: Path) -> None:
    import yfinance as yf

    histories = {
        "AAA": _make_history(
            "AAA",
            [
                (date(2024, 1, 2), 100.0),
                (date(2024, 1, 3), 101.0),
            ],
        ),
        "BBB": _make_history(
            "BBB",
            [
                (date(2024, 1, 2), 200.0),
                (date(2024, 1, 3), 202.0),
            ],
        ),
    }

    class _Ticker:
        def __init__(self, ticker: str) -> None:
            self.ticker = ticker

        def history(self, *, start: str, end: str) -> Any:
            return histories.get(self.ticker)

    monkeypatch.setattr("bottlewatch.app.ingest.prices.yf", yf)
    monkeypatch.setattr(yf, "Ticker", _Ticker)
    monkeypatch.setattr("bottlewatch.app.ingest.prices.time.sleep", lambda *_: None)

    bars = fetch_prices_yfinance(
        ["AAA", "BBB"],
        date(2024, 1, 2),
        date(2024, 1, 3),
    )
    assert len(bars) == 4
    assert bars[0] == PriceBar("AAA", date(2024, 1, 2), 100.0)
    assert bars[-1] == PriceBar("BBB", date(2024, 1, 3), 202.0)


def test_yfinance_fetcher_prefers_adj_close(monkeypatch: Any) -> None:
    import yfinance as yf
    import pandas as pd

    index = pd.DatetimeIndex([date(2024, 1, 2)])
    df = pd.DataFrame({"Close": [100.0], "Adj Close": [99.5]}, index=index)

    class _Ticker:
        def __init__(self, ticker: str) -> None:
            self.ticker = ticker

        def history(self, *, start: str, end: str) -> Any:
            return df

    monkeypatch.setattr("bottlewatch.app.ingest.prices.yf", yf)
    monkeypatch.setattr(yf, "Ticker", _Ticker)
    monkeypatch.setattr("bottlewatch.app.ingest.prices.time.sleep", lambda *_: None)

    bars = fetch_prices_yfinance(["AAA"], date(2024, 1, 1), date(2024, 1, 3))
    assert bars == [PriceBar("AAA", date(2024, 1, 2), 99.5)]


def test_yfinance_fetcher_ignores_empty_or_failed_tickers(monkeypatch: Any) -> None:
    import yfinance as yf
    import pandas as pd

    class _Ticker:
        def __init__(self, ticker: str) -> None:
            self.ticker = ticker

        def history(self, *, start: str, end: str) -> Any:
            return pd.DataFrame()

    monkeypatch.setattr("bottlewatch.app.ingest.prices.yf", yf)
    monkeypatch.setattr(yf, "Ticker", _Ticker)
    monkeypatch.setattr("bottlewatch.app.ingest.prices.time.sleep", lambda *_: None)

    bars = fetch_prices_yfinance(["AAA"], date(2024, 1, 1), date(2024, 1, 3))
    assert bars == []


# ---------------------------------------------------------------------------
# Alpha Vantage fetcher
# ---------------------------------------------------------------------------


def _av_payload(dates: list[tuple[date, float]]) -> dict[str, Any]:
    series: dict[str, dict[str, str]] = {}
    for d, close in dates:
        series[d.isoformat()] = {
            "1. open": str(close),
            "2. high": str(close),
            "3. low": str(close),
            "4. close": str(close),
            "5. adjusted close": str(close),
            "6. volume": "1000",
            "7. dividend amount": "0",
            "8. split coefficient": "1",
        }
    return {"Time Series (Daily)": series}


def test_alphavantage_fetcher_parses_adjusted_close(monkeypatch: Any) -> None:
    monkeypatch.setattr("bottlewatch.app.ingest.prices.time.sleep", lambda *_: None)

    with respx.mock(base_url="https://www.alphavantage.co") as mock:
        route = mock.get("/query").mock(
            side_effect=[
                Response(200, json=_av_payload([(date(2024, 1, 2), 100.0), (date(2024, 1, 3), 101.0)])),
                Response(200, json=_av_payload([(date(2024, 1, 2), 200.0)])),
            ]
        )
        bars = fetch_prices_alphavantage(
            ["AAA", "BBB"],
            api_key="test-key",
            start=date(2024, 1, 1),
            end=date(2024, 1, 3),
        )

    assert route.call_count == 2
    assert len(bars) == 3
    assert bars[0] == PriceBar("AAA", date(2024, 1, 2), 100.0)
    assert bars[-1] == PriceBar("BBB", date(2024, 1, 2), 200.0)


def test_fetch_prices_alphavantage_requires_key() -> None:
    with pytest.raises(ValueError, match="PRICE_API_KEY"):
        fetch_prices(
            source="alphavantage",
            tickers=["AAA"],
            start=date(2024, 1, 1),
            end=date(2024, 1, 3),
            api_key=None,
        )


def test_fetch_prices_csv_source_returns_empty() -> None:
    assert fetch_prices("csv", ["AAA"], date(2024, 1, 1), date(2024, 1, 3)) == []


def test_fetch_prices_unsupported_source_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        fetch_prices("not_a_source", ["AAA"], date(2024, 1, 1), date(2024, 1, 3))


# ---------------------------------------------------------------------------
# CSV merge
# ---------------------------------------------------------------------------


def test_merge_prices_csv_merges_and_sorts(tmp_path: Path) -> None:
    csv_path = tmp_path / "prices.csv"
    csv_path.write_text("ticker,date,close\nAAA,2024-01-02,100.00\nBBB,2024-01-02,200.00\n")
    fetched = [
        PriceBar("AAA", date(2024, 1, 2), 100.50),
        PriceBar("AAA", date(2024, 1, 3), 101.00),
        PriceBar("CCC", date(2024, 1, 2), 300.00),
    ]
    rows_written = merge_prices_csv(fetched, csv_path)
    assert rows_written == 4

    provider = CsvPriceProvider(csv_path)
    aaa = provider.get_prices("AAA", date(2024, 1, 1), date(2024, 12, 31))
    assert len(aaa) == 2
    assert aaa[0].close == 100.50
    assert aaa[1].date == date(2024, 1, 3)
    assert provider.get_prices("BBB", date(2024, 1, 1), date(2024, 12, 31))[0].close == 200.00
    assert provider.get_prices("CCC", date(2024, 1, 1), date(2024, 12, 31))[0].close == 300.00


# ---------------------------------------------------------------------------
# refresh job
# ---------------------------------------------------------------------------


def test_refresh_prices_csv_source_is_noop(tmp_path: Path) -> None:
    universe = _universe_csv(tmp_path)
    output = tmp_path / "prices.csv"
    settings = Settings(
        price_data_source="csv",
        database_url="sqlite:///:memory:",
        refresh_log_path=tmp_path / "refresh.log",
        prices_csv_path=output,
    )
    result = run_refresh_prices(
        settings=settings,
        universe_path=universe,
        output_path=output,
    )
    assert result["source"] == "csv"
    assert result["rows_written"] == 0
    assert not output.exists()


def test_refresh_prices_yfinance_source_writes_csv(monkeypatch: Any, tmp_path: Path) -> None:
    universe = _universe_csv(tmp_path)
    output = tmp_path / "prices.csv"
    settings = Settings(
        price_data_source="yfinance",
        database_url="sqlite:///:memory:",
        refresh_log_path=tmp_path / "refresh.log",
        prices_csv_path=output,
    )

    fake_bars = [
        PriceBar("AAA", date(2024, 1, 2), 100.0),
        PriceBar("BBB", date(2024, 1, 2), 200.0),
    ]
    monkeypatch.setattr(
        "bottlewatch.app.ingest.prices.fetch_prices",
        lambda **_kwargs: fake_bars,
    )

    result = run_refresh_prices(
        settings=settings,
        universe_path=universe,
        output_path=output,
    )
    assert result["source"] == "yfinance"
    assert result["tickers"] == 2
    assert result["rows_written"] == 2

    provider = CsvPriceProvider(output)
    assert provider.get_prices("AAA", date(2024, 1, 1), date(2024, 12, 31))[0].close == 100.0
    assert provider.get_prices("BBB", date(2024, 1, 1), date(2024, 12, 31))[0].close == 200.0


def test_refresh_prices_uses_date_window_from_lookback(tmp_path: Path, monkeypatch: Any) -> None:
    universe = _universe_csv(tmp_path)
    output = tmp_path / "prices.csv"
    today = date.today()
    expected_start = today - timedelta(days=30)
    captured: dict[str, Any] = {}

    def _fake_fetch(
        *, source: str, tickers: list[str], start: date, end: date, api_key: Any, progress: Any
    ) -> list[PriceBar]:
        captured.update({"source": source, "tickers": tickers, "start": start, "end": end})
        return []

    monkeypatch.setattr("bottlewatch.app.ingest.prices.fetch_prices", _fake_fetch)

    settings = Settings(
        price_data_source="yfinance",
        price_lookback_days=30,
        database_url="sqlite:///:memory:",
        refresh_log_path=tmp_path / "refresh.log",
        prices_csv_path=output,
    )
    run_refresh_prices(
        settings=settings,
        universe_path=universe,
        output_path=output,
    )
    assert captured["start"] == expected_start
    assert captured["end"] == today


def test_refresh_prices_job_run_wires_defaults(tmp_path: Path, monkeypatch: Any) -> None:
    from bottlewatch.jobs.refresh_prices import run

    captured: dict[str, Any] = {}

    def _fake_run_refresh_prices(
        *, settings: Any, universe_path: Any, output_path: Any, source: Any, start: Any, end: Any, progress: Any
    ) -> dict[str, Any]:
        captured.update(
            {
                "universe_path": universe_path,
                "output_path": output_path,
                "source": source,
            }
        )
        return {
            "source": "csv",
            "tickers": 0,
            "rows_written": 0,
            "path": str(output_path),
            "detail": "",
        }

    monkeypatch.setattr("bottlewatch.jobs.refresh_prices.run_refresh_prices", _fake_run_refresh_prices)

    settings = Settings(
        price_data_source="csv",
        database_url="sqlite:///:memory:",
        refresh_log_path=tmp_path / "refresh.log",
        prices_csv_path=tmp_path / "prices.csv",
    )
    result = run(settings=settings)
    assert result["source"] == "csv"
    assert captured["output_path"] == settings.prices_csv_path
    assert captured["source"] is None
