"""Tests for the ticker-level basket engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pytest

from bottlewatch.app.backtest.baskets import _load_universe, build_baskets
from bottlewatch.app.score.regime import Regime


@dataclass(frozen=True)
class _Row:
    ticker: str
    exchange: str
    name: str
    segment: str
    subsegment: str | None
    exposure_pct: float
    mcap_usd: float


def _write_universe(tmp_path: Path, rows: list[_Row]) -> Path:
    path = tmp_path / "universe.csv"
    header = "ticker,exchange,name,segment,subsegment,exposure_pct,market_cap_bucket,mcap_usd,currency_hedge,notes"
    lines = [header]
    for r in rows:
        lines.append(
            f"{r.ticker},NASDAQ,{r.name},{r.segment},{r.subsegment or ''},"
            f"{int(r.exposure_pct * 100)},large,{int(r.mcap_usd)},USD,note"
        )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def test_long_basket_selects_top_segment_and_tickers(tmp_path: Path) -> None:
    universe = _write_universe(
        tmp_path,
        [
            _Row("AAA", "NASDAQ", "A", "seg_a", "sub", 0.8, 3_000_000_000),
            _Row("BBB", "NASDAQ", "B", "seg_a", "sub", 0.7, 3_000_000_000),
            _Row("CCC", "NASDAQ", "C", "seg_a", "sub", 0.4, 3_000_000_000),  # low exposure
            _Row("DDD", "NASDAQ", "D", "seg_b", "sub", 0.8, 3_000_000_000),
        ],
    )
    scores = {
        "seg_a": {"b": 80.0, "momentum": 10.0, "regime": Regime.PEAKED},
        "seg_b": {"b": 60.0, "momentum": 5.0, "regime": Regime.STABLE},
    }
    baskets = build_baskets(
        eval_date=date(2025, 1, 1),
        horizon="near",
        scores=scores,
        universe_rows=_load_universe(universe),
        prices={},
        forward_days=90,
    )
    long = baskets["long"]
    assert long.side == "long"
    assert long.segments == ["seg_a"]
    assert {e.ticker for e in long.tickers} == {"AAA", "BBB"}
    assert long.equal_weight_return is None  # no prices provided


def test_long_basket_includes_second_segment_within_proximity(tmp_path: Path) -> None:
    universe = _write_universe(
        tmp_path,
        [
            _Row("AAA", "NASDAQ", "A", "seg_a", "sub", 0.8, 3_000_000_000),
            _Row("BBB", "NASDAQ", "B", "seg_b", "sub", 0.8, 3_000_000_000),
        ],
    )
    scores = {
        "seg_a": {"b": 80.0, "momentum": 10.0, "regime": Regime.PEAKED},
        "seg_b": {"b": 75.0, "momentum": 5.0, "regime": Regime.STABLE},
    }
    baskets = build_baskets(
        eval_date=date(2025, 1, 1),
        horizon="near",
        scores=scores,
        universe_rows=_load_universe(universe),
        prices={},
        forward_days=90,
    )
    assert set(baskets["long"].segments) == {"seg_a", "seg_b"}


def test_long_basket_excludes_resolving(tmp_path: Path) -> None:
    universe = _write_universe(
        tmp_path,
        [
            _Row("AAA", "NASDAQ", "A", "seg_a", "sub", 0.8, 3_000_000_000),
        ],
    )
    scores = {
        "seg_a": {"b": 80.0, "momentum": -20.0, "regime": Regime.RESOLVING},
    }
    baskets = build_baskets(
        eval_date=date(2025, 1, 1),
        horizon="near",
        scores=scores,
        universe_rows=_load_universe(universe),
        prices={},
        forward_days=90,
    )
    assert baskets["long"].segments == []
    assert baskets["long"].tickers == []


def test_short_basket_selects_only_resolving(tmp_path: Path) -> None:
    universe = _write_universe(
        tmp_path,
        [
            _Row("AAA", "NASDAQ", "A", "seg_a", "sub", 0.8, 3_000_000_000),
            _Row("BBB", "NASDAQ", "B", "seg_b", "sub", 0.8, 3_000_000_000),
        ],
    )
    scores = {
        "seg_a": {"b": 80.0, "momentum": -30.0, "regime": Regime.RESOLVING},
        "seg_b": {"b": 75.0, "momentum": -10.0, "regime": Regime.RESOLVING},
    }
    baskets = build_baskets(
        eval_date=date(2025, 1, 1),
        horizon="near",
        scores=scores,
        universe_rows=_load_universe(universe),
        prices={},
        forward_days=90,
    )
    short = baskets["short"]
    assert short.segments == ["seg_a"]  # higher B * |B'|, and seg_b B is 5 pts away
    assert {e.ticker for e in short.tickers} == {"AAA"}


def test_basket_forward_return(tmp_path: Path) -> None:
    universe = _write_universe(
        tmp_path,
        [
            _Row("AAA", "NASDAQ", "A", "seg_a", "sub", 0.8, 3_000_000_000),
        ],
    )
    scores = {
        "seg_a": {"b": 80.0, "momentum": 10.0, "regime": Regime.PEAKED},
    }
    prices = {
        "AAA": [
            (date(2025, 1, 1), 100.0),
            (date(2025, 4, 1), 110.0),
        ]
    }
    baskets = build_baskets(
        eval_date=date(2025, 1, 1),
        horizon="near",
        scores=scores,
        universe_rows=_load_universe(universe),
        prices=prices,
        forward_days=90,
    )
    long = baskets["long"]
    assert long.equal_weight_return == pytest.approx(0.10)
    assert long.net_return == pytest.approx(0.099)
    assert long.hit_rate == pytest.approx(1.0)
    assert long.max_drawdown == pytest.approx(0.0)
    assert long.volatility is None  # only one ticker
    assert long.coverage == 1.0


def test_basket_risk_metrics_with_multiple_tickers(tmp_path: Path) -> None:
    universe = _write_universe(
        tmp_path,
        [
            _Row("AAA", "NASDAQ", "A", "seg_a", "sub", 0.8, 3_000_000_000),
            _Row("BBB", "NASDAQ", "B", "seg_a", "sub", 0.7, 3_000_000_000),
        ],
    )
    scores = {"seg_a": {"b": 80.0, "momentum": 10.0, "regime": Regime.PEAKED}}
    prices = {
        "AAA": [(date(2025, 1, 1), 100.0), (date(2025, 4, 1), 120.0)],
        "BBB": [(date(2025, 1, 1), 100.0), (date(2025, 4, 1), 100.0)],
    }
    baskets = build_baskets(
        eval_date=date(2025, 1, 1),
        horizon="near",
        scores=scores,
        universe_rows=_load_universe(universe),
        prices=prices,
        forward_days=90,
    )
    long = baskets["long"]
    assert long.equal_weight_return == pytest.approx(0.10)
    assert long.hit_rate == pytest.approx(0.5)
    assert long.net_return == pytest.approx(0.10 - 0.001 * 2)
    assert long.volatility is not None
    assert long.max_drawdown == pytest.approx(0.0)


def test_basket_sector_neutral_weighting(tmp_path: Path) -> None:
    universe = _write_universe(
        tmp_path,
        [
            _Row("A1", "NASDAQ", "A1", "seg_a", "sub", 0.8, 3_000_000_000),
            _Row("A2", "NASDAQ", "A2", "seg_a", "sub", 0.8, 3_000_000_000),
            _Row("B1", "NASDAQ", "B1", "seg_b", "sub", 0.8, 3_000_000_000),
        ],
    )
    scores = {
        "seg_a": {"b": 80.0, "momentum": 10.0, "regime": Regime.PEAKED},
        "seg_b": {"b": 75.0, "momentum": 5.0, "regime": Regime.STABLE},
    }
    prices = {
        "A1": [(date(2025, 1, 1), 100.0), (date(2025, 4, 1), 120.0)],
        "A2": [(date(2025, 1, 1), 100.0), (date(2025, 4, 1), 120.0)],
        "B1": [(date(2025, 1, 1), 100.0), (date(2025, 4, 1), 100.0)],
    }
    baskets = build_baskets(
        eval_date=date(2025, 1, 1),
        horizon="near",
        scores=scores,
        universe_rows=_load_universe(universe),
        prices=prices,
        forward_days=90,
        sector_neutral=True,
    )
    long = baskets["long"]
    assert long.sector_neutral is True
    weights = {e.ticker: e.weight for e in long.tickers}
    assert weights["A1"] == pytest.approx(0.25)
    assert weights["A2"] == pytest.approx(0.25)
    assert weights["B1"] == pytest.approx(0.5)
    # Equal segment weight makes the flat segment hurt more.
    assert long.equal_weight_return == pytest.approx(0.10)


def test_basket_equal_weight_without_sector_neutral(tmp_path: Path) -> None:
    universe = _write_universe(
        tmp_path,
        [
            _Row("A1", "NASDAQ", "A1", "seg_a", "sub", 0.8, 3_000_000_000),
            _Row("A2", "NASDAQ", "A2", "seg_a", "sub", 0.8, 3_000_000_000),
            _Row("B1", "NASDAQ", "B1", "seg_b", "sub", 0.8, 3_000_000_000),
        ],
    )
    scores = {
        "seg_a": {"b": 80.0, "momentum": 10.0, "regime": Regime.PEAKED},
        "seg_b": {"b": 75.0, "momentum": 5.0, "regime": Regime.STABLE},
    }
    prices = {
        "A1": [(date(2025, 1, 1), 100.0), (date(2025, 4, 1), 120.0)],
        "A2": [(date(2025, 1, 1), 100.0), (date(2025, 4, 1), 120.0)],
        "B1": [(date(2025, 1, 1), 100.0), (date(2025, 4, 1), 100.0)],
    }
    baskets = build_baskets(
        eval_date=date(2025, 1, 1),
        horizon="near",
        scores=scores,
        universe_rows=_load_universe(universe),
        prices=prices,
        forward_days=90,
        sector_neutral=False,
    )
    long = baskets["long"]
    assert long.sector_neutral is False
    weights = {e.ticker: e.weight for e in long.tickers}
    assert weights["A1"] == pytest.approx(1.0 / 3)
    assert weights["A2"] == pytest.approx(1.0 / 3)
    assert weights["B1"] == pytest.approx(1.0 / 3)
    assert long.equal_weight_return == pytest.approx((0.2 + 0.2 + 0.0) / 3)


# ---------------------------------------------------------------------------
# Point-in-time as-of membership gate (universe-leak fix)
# ---------------------------------------------------------------------------


def test_not_yet_listed_ticker_excluded_as_of(tmp_path: Path) -> None:
    """Property 1: a ticker whose first price bar is AFTER eval_date is not in
    the basket built at eval_date (it wasn't trading then).
    """
    universe = _write_universe(
        tmp_path,
        [
            _Row("LIVE", "NASDAQ", "Live", "seg_a", "sub", 0.8, 3_000_000_000),
            _Row("IPO", "NASDAQ", "Ipo", "seg_a", "sub", 0.8, 3_000_000_000),
        ],
    )
    scores = {"seg_a": {"b": 80.0, "momentum": 10.0, "regime": Regime.PEAKED}}
    prices = {
        "LIVE": [(date(2025, 1, 1), 100.0), (date(2025, 4, 1), 110.0)],
        # IPO's first bar is AFTER the eval date → not listed as-of 2025-01-01.
        "IPO": [(date(2025, 3, 1), 50.0), (date(2025, 6, 1), 60.0)],
    }
    baskets = build_baskets(
        eval_date=date(2025, 1, 1),
        horizon="near",
        scores=scores,
        universe_rows=_load_universe(universe),
        prices=prices,
        forward_days=90,
    )
    tickers = {e.ticker for e in baskets["long"].tickers}
    assert tickers == {"LIVE"}  # IPO excluded — not trading at eval_date


def test_listed_ticker_retained_as_of(tmp_path: Path) -> None:
    """Property 2: a ticker trading at-or-before eval_date is included."""
    universe = _write_universe(
        tmp_path,
        [_Row("LIVE", "NASDAQ", "Live", "seg_a", "sub", 0.8, 3_000_000_000)],
    )
    scores = {"seg_a": {"b": 80.0, "momentum": 10.0, "regime": Regime.PEAKED}}
    prices = {"LIVE": [(date(2024, 12, 1), 90.0), (date(2025, 4, 1), 110.0)]}
    baskets = build_baskets(
        eval_date=date(2025, 1, 1),
        horizon="near",
        scores=scores,
        universe_rows=_load_universe(universe),
        prices=prices,
        forward_days=90,
    )
    assert {e.ticker for e in baskets["long"].tickers} == {"LIVE"}


def test_ticker_with_no_prices_excluded_when_prices_present(tmp_path: Path) -> None:
    """Property 3: a selected-eligible ticker with no price series at all is
    excluded once any price data is provided (can't confirm it was trading).
    """
    universe = _write_universe(
        tmp_path,
        [
            _Row("LIVE", "NASDAQ", "Live", "seg_a", "sub", 0.8, 3_000_000_000),
            _Row("GHOST", "NASDAQ", "Ghost", "seg_a", "sub", 0.8, 3_000_000_000),
        ],
    )
    scores = {"seg_a": {"b": 80.0, "momentum": 10.0, "regime": Regime.PEAKED}}
    prices = {"LIVE": [(date(2025, 1, 1), 100.0), (date(2025, 4, 1), 110.0)]}
    baskets = build_baskets(
        eval_date=date(2025, 1, 1),
        horizon="near",
        scores=scores,
        universe_rows=_load_universe(universe),
        prices=prices,
        forward_days=90,
    )
    assert {e.ticker for e in baskets["long"].tickers} == {"LIVE"}  # GHOST has no prices
