"""Tests for the walk-forward backtest job and its pure helpers."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import sessionmaker

from bottlewatch.app.backtest.prices import CsvPriceProvider, PriceBar
from bottlewatch.app.db import ScoreHistory, session_scope
from bottlewatch.config import Settings
from bottlewatch.jobs.backtest import (
    BacktestReport,
    _b_at,
    _eval_dates,
    _forward_return,
    _rank,
    run_backtest,
    spearman,
)


# ---------------------------------------------------------------------------
# Spearman math (pure)
# ---------------------------------------------------------------------------


def test_rank_basic_no_ties() -> None:
    assert _rank([10.0, 30.0, 20.0]) == [1.0, 3.0, 2.0]


def test_rank_with_ties_uses_average() -> None:
    # 4 elements, two pairs of ties: (1, 2) tied at ranks 1.5, (4) at rank 4.
    assert _rank([10.0, 10.0, 30.0, 40.0]) == [1.5, 1.5, 3.0, 4.0]


def test_spearman_perfect_positive() -> None:
    rho, p = spearman([1.0, 2.0, 3.0, 4.0, 5.0], [10.0, 20.0, 30.0, 40.0, 50.0])
    assert rho == pytest.approx(1.0)
    assert p is not None and p < 0.001


def test_spearman_perfect_negative() -> None:
    rho, _ = spearman([1.0, 2.0, 3.0, 4.0, 5.0], [50.0, 40.0, 30.0, 20.0, 10.0])
    assert rho == pytest.approx(-1.0)


def test_spearman_zero_variance_returns_none() -> None:
    # All y values are the same → no ranking possible.
    rho, p = spearman([1.0, 2.0, 3.0], [5.0, 5.0, 5.0])
    assert rho is None
    assert p is None


def test_spearman_short_input_returns_no_p_value() -> None:
    rho, p = spearman([1.0, 2.0], [10.0, 20.0])
    assert rho == pytest.approx(1.0)
    # n < 4 → no p-value (we only approximate via normal for n >= 4).
    assert p is None


def test_spearman_mismatched_lengths_raises() -> None:
    with pytest.raises(ValueError, match="same length"):
        spearman([1.0, 2.0], [10.0])


# ---------------------------------------------------------------------------
# CsvPriceProvider
# ---------------------------------------------------------------------------


def test_csv_provider_missing_file_returns_empty(tmp_path: Path) -> None:
    p = CsvPriceProvider(tmp_path / "missing.csv")
    assert p.get_prices("NVDA", date(2024, 1, 1), date(2024, 12, 31)) == []


def test_csv_provider_unknown_ticker_returns_empty(tmp_path: Path) -> None:
    p_csv = tmp_path / "prices.csv"
    p_csv.write_text("ticker,date,close\nNVDA,2024-06-01,100.0\n")
    p = CsvPriceProvider(p_csv)
    assert p.get_prices("UNKNOWN", date(2024, 1, 1), date(2024, 12, 31)) == []


def test_csv_provider_filters_by_date_window(tmp_path: Path) -> None:
    p_csv = tmp_path / "prices.csv"
    p_csv.write_text(
        "ticker,date,close\n"
        "NVDA,2024-01-01,100.0\n"
        "NVDA,2024-06-01,110.0\n"
        "NVDA,2024-12-31,120.0\n"
        "NVDA,2025-01-01,125.0\n"
    )
    p = CsvPriceProvider(p_csv)
    bars = p.get_prices("NVDA", date(2024, 6, 1), date(2024, 12, 31))
    assert [b.date for b in bars] == [date(2024, 6, 1), date(2024, 12, 31)]
    assert [b.close for b in bars] == [110.0, 120.0]


def test_csv_provider_sorts_bars_ascending(tmp_path: Path) -> None:
    p_csv = tmp_path / "prices.csv"
    p_csv.write_text("ticker,date,close\nNVDA,2024-06-01,110.0\nNVDA,2024-01-01,100.0\n")
    p = CsvPriceProvider(p_csv)
    bars = p.get_prices("NVDA", date(2024, 1, 1), date(2024, 12, 31))
    assert bars[0].date < bars[1].date


def test_csv_provider_skips_malformed_rows(tmp_path: Path) -> None:
    p_csv = tmp_path / "prices.csv"
    p_csv.write_text(
        "ticker,date,close\n"
        "NVDA,2024-06-01,110.0\n"
        ",2024-07-01,120.0\n"  # missing ticker
        "NVDA,,130.0\n"  # missing date
        "NVDA,not-a-date,140.0\n"  # bad date
        "NVDA,2024-08-01,not-a-number\n"  # bad close
        "NVDA,2024-09-01,150.0\n"
    )
    p = CsvPriceProvider(p_csv)
    bars = p.get_prices("NVDA", date(2024, 1, 1), date(2024, 12, 31))
    assert [b.date for b in bars] == [date(2024, 6, 1), date(2024, 9, 1)]


# ---------------------------------------------------------------------------
# Pure helpers: _b_at, _forward_return, _eval_dates
# ---------------------------------------------------------------------------


def test_b_at_returns_most_recent_value_at_or_before_target() -> None:
    series = [
        (datetime(2024, 1, 1), 50.0),
        (datetime(2024, 4, 1), 55.0),
        (datetime(2024, 7, 1), 60.0),
    ]
    assert _b_at(series, date(2024, 6, 1)) == 55.0
    assert _b_at(series, date(2024, 1, 1)) == 50.0
    assert _b_at(series, date(2024, 7, 1)) == 60.0
    assert _b_at(series, date(2023, 1, 1)) is None


def test_forward_return_computes_pct_change() -> None:
    bars = [
        PriceBar("NVDA", date(2024, 1, 1), 100.0),
        PriceBar("NVDA", date(2024, 4, 1), 110.0),
        PriceBar("NVDA", date(2024, 7, 1), 120.0),
    ]
    # 2024-01-01 + 91 calendar days = 2024-04-01 (Apr 1 is the 91st day).
    # 90 days = 2024-03-31, which has no bar between → None.
    assert _forward_return(bars, date(2024, 1, 1), 90) is None
    assert _forward_return(bars, date(2024, 1, 1), 91) == pytest.approx(0.10)
    # 2024-01-01 + 182 calendar days = 2024-07-01.
    assert _forward_return(bars, date(2024, 1, 1), 182) == pytest.approx(0.20)


def test_forward_return_returns_none_when_missing() -> None:
    bars = [PriceBar("NVDA", date(2024, 1, 1), 100.0)]
    # No bar at t + 90 → None.
    assert _forward_return(bars, date(2024, 1, 1), 90) is None


def test_eval_dates_generates_monthly_steps() -> None:
    dates = _eval_dates(date(2024, 1, 1), date(2024, 4, 15), step_days=30)
    # With step_days=30 starting Jan 1, the sequence is:
    # 2024-01-01, 2024-01-31, 2024-03-01, 2024-03-31. Day 1 + 30n
    # does not land on month boundaries; we just check the count
    # and that the first and last are inside the window.
    assert dates[0] == date(2024, 1, 1)
    assert dates[-1] <= date(2024, 4, 15)
    assert dates[-1] >= date(2024, 3, 1)
    assert len(dates) >= 4


def test_eval_dates_inverted_returns_empty() -> None:
    assert _eval_dates(date(2024, 6, 1), date(2024, 1, 1)) == []


# ---------------------------------------------------------------------------
# run_backtest integration: synthetic prices + synthetic score_history
# ---------------------------------------------------------------------------


def _seed_synthetic_universe(tmp_path: Path) -> Path:
    """Two segments × two tickers each. Returns the path to a tiny universe CSV."""
    p = tmp_path / "universe.csv"
    p.write_text(
        "ticker,exchange,name,segment,subsegment,exposure_pct,market_cap_bucket,mcap_usd,currency_hedge,notes\n"
        "AAA,NASDAQ,AAA Corp,segment_high,sub_a,80,large,1000000000,USD,High-B segment\n"
        "BBB,NASDAQ,BBB Corp,segment_high,sub_b,70,large,2000000000,USD,High-B segment\n"
        "CCC,NASDAQ,CCC Corp,segment_low,sub_c,80,large,1000000000,USD,Low-B segment\n"
        "DDD,NASDAQ,DDD Corp,segment_low,sub_d,70,large,2000000000,USD,Low-B segment\n"
    )
    return p


def _write_synthetic_prices(tmp_path: Path) -> Path:
    """Prices that drift up faster for the "high-B" segment (AAA, BBB) than the low-B ones."""
    p = tmp_path / "prices.csv"
    rows: list[str] = ["ticker,date,close"]
    # Daily bars from 2024-01-01 to 2025-12-31. 730 days.
    start = date(2024, 1, 1)
    for i in range(730):
        d = start + timedelta(days=i)
        # High-B tickers: drift up 0.10% per day → ~+101% over 2y
        rows.append(f"AAA,{d.isoformat()},{100.0 * (1.001**i):.4f}")
        rows.append(f"BBB,{d.isoformat()},{100.0 * (1.001**i):.4f}")
        # Low-B tickers: drift up 0.03% per day → ~+23% over 2y
        rows.append(f"CCC,{d.isoformat()},{100.0 * (1.0003**i):.4f}")
        rows.append(f"DDD,{d.isoformat()},{100.0 * (1.0003**i):.4f}")
    p.write_text("\n".join(rows) + "\n")
    return p


def _seed_score_history(factory: sessionmaker, high: float, low: float, horizon: str) -> None:
    """Append 6 monthly score_history rows for the two segments.

    We bypass the recompute job's signal-driven formula and write
    ScoreHistory directly: the backtest only reads from the table.
    """
    base = datetime(2024, 6, 1, tzinfo=timezone.utc).replace(tzinfo=None)
    rows = []
    for i in range(12):
        ts = base + timedelta(days=30 * i)
        for seg, b in (("segment_high", high), ("segment_low", low)):
            rows.append(
                ScoreHistory(
                    segment=seg,
                    horizon=horizon,
                    computed_at=ts,
                    b=b,
                    momentum=0.0,
                    regime="STABLE",
                )
            )
    with session_scope(factory) as session:
        # Clean any prior runs so the test is deterministic.
        session.execute(delete(ScoreHistory).where(ScoreHistory.segment.in_(["segment_high", "segment_low"])))
        for r in rows:
            session.add(r)


def test_run_backtest_with_synthetic_positive_signal(settings: Settings, factory: sessionmaker, tmp_path: Path) -> None:
    """High B segment outperforms low B segment → overall Spearman should be positive."""
    universe = _seed_synthetic_universe(tmp_path)
    prices_path = _write_synthetic_prices(tmp_path)
    _seed_score_history(factory, high=0.9, low=0.3, horizon="near")

    prices = CsvPriceProvider(prices_path)
    report = run_backtest(
        prices=prices,
        factory=factory,
        universe_path=universe,
        start=date(2024, 9, 1),
        end=date(2025, 6, 1),
        forward_days=90,
        horizon="near",
    )

    assert isinstance(report, BacktestReport)
    assert report.horizon == "near"
    assert report.forward_days == 90
    # 9 months × 4 tickers = 36 (ticker, segment, t) tuples.
    assert report.n_eval_dates >= 8
    assert report.n_eval_points >= 30
    # The overall Spearman should be strongly positive: high-B segment
    # tickers grew faster than low-B ones, and B ranks them correctly.
    assert report.overall.rho is not None
    assert report.overall.rho > 0.3
    # Per-segment: only 2 segments, each with one B value, so per-segment
    # Spearman is None (zero variance within a segment). That's correct.
    seg_names = {s.segment for s in report.per_segment}
    assert seg_names == {"segment_high", "segment_low"}
    for s in report.per_segment:
        assert s.n >= 8
        # Within a single segment, B is constant, so rho is None.
        assert s.rho is None


def test_run_backtest_empty_universe_returns_empty_report(
    settings: Settings, factory: sessionmaker, tmp_path: Path
) -> None:
    """No universe rows → empty report, not a crash."""
    empty_universe = tmp_path / "empty.csv"
    empty_universe.write_text(
        "ticker,exchange,name,segment,subsegment,exposure_pct,market_cap_bucket,mcap_usd,currency_hedge,notes\n"
    )
    prices = CsvPriceProvider(tmp_path / "no_prices.csv")
    report = run_backtest(
        prices=prices,
        factory=factory,
        universe_path=empty_universe,
        start=date(2024, 1, 1),
        end=date(2024, 12, 31),
    )
    assert report.n_eval_points == 0
    assert report.overall.n == 0
    assert report.overall.rho is None


def test_run_backtest_handles_no_score_history_gracefully(
    settings: Settings, factory: sessionmaker, tmp_path: Path
) -> None:
    """When score_history has no rows for the segment, B is None → no eval points."""
    universe = _seed_synthetic_universe(tmp_path)
    prices_path = _write_synthetic_prices(tmp_path)
    # No _seed_score_history call — table is empty for our test segments.
    prices = CsvPriceProvider(prices_path)
    report = run_backtest(
        prices=prices,
        factory=factory,
        universe_path=universe,
        start=date(2024, 9, 1),
        end=date(2025, 6, 1),
    )
    assert report.n_eval_points == 0
    assert report.overall.rho is None


def test_run_backtest_handles_no_prices_gracefully(settings: Settings, factory: sessionmaker, tmp_path: Path) -> None:
    """When prices are missing for a ticker, R is None → that tuple is skipped."""
    universe = _seed_synthetic_universe(tmp_path)
    _seed_score_history(factory, high=0.9, low=0.3, horizon="near")
    empty_prices = tmp_path / "prices.csv"
    empty_prices.write_text("ticker,date,close\n")
    prices = CsvPriceProvider(empty_prices)
    report = run_backtest(
        prices=prices,
        factory=factory,
        universe_path=universe,
        start=date(2024, 9, 1),
        end=date(2025, 6, 1),
    )
    assert report.n_eval_points == 0


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------


def test_cli_writes_json_report_and_exits_zero(tmp_path: Path) -> None:
    """The CLI runs end-to-end on a synthetic dataset, writes a JSON report, exits 0.

    The CLI subprocess opens its own DB connection, so we use a
    file-based SQLite in a tmp dir (rather than the in-memory
    fixture from conftest) and pre-populate the schema + score
    history. The subprocess then re-opens the same file and reads
    the seeded rows.
    """
    from bottlewatch.app.db import init_schema, make_engine, make_session_factory

    universe = _seed_synthetic_universe(tmp_path)
    prices_path = _write_synthetic_prices(tmp_path)
    output = tmp_path / "report.json"
    db_path = tmp_path / "backtest.db"
    db_url = f"sqlite:///{db_path}"

    # Set up the DB once in this process: create the schema and seed.
    engine = make_engine(db_url)
    init_schema(engine)
    factory = make_session_factory(engine)
    _seed_score_history(factory, high=0.9, low=0.3, horizon="near")
    engine.dispose()

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "bottlewatch.jobs.backtest",
            "--prices",
            str(prices_path),
            "--universe",
            str(universe),
            "--start",
            "2024-09-01",
            "--end",
            "2025-06-01",
            "--forward-days",
            "90",
            "--horizon",
            "near",
            "--output",
            str(output),
            "--database-url",
            db_url,
        ],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[3]),
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert output.exists()
    payload = json.loads(output.read_text())
    assert payload["horizon"] == "near"
    assert payload["forward_days"] == 90
    assert payload["n_eval_points"] >= 30
    assert payload["overall"]["rho"] is not None
    assert payload["overall"]["rho"] > 0.3
