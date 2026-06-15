"""Ticker-level conviction basket engine (methodology §7.9).

Builds long, short, and watchlist baskets at each evaluation date from
segment scores and the universe CSV.
"""

from __future__ import annotations

import csv
import math
import statistics
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

from bottlewatch.app.score.regime import Regime


@dataclass(frozen=True)
class TickerBasketEntry:
    """One selected ticker inside a basket."""

    ticker: str
    name: str
    segment: str
    exposure_pct: float
    mcap_usd: float
    score: float
    score_contribution: float
    weight: float = 1.0


@dataclass(frozen=True)
class Basket:
    """A long, short, or watchlist basket at one evaluation date."""

    side: str  # "long" | "short" | "watchlist"
    eval_date: date
    horizon: str
    segments: list[str]
    tickers: list[TickerBasketEntry]
    equal_weight_return: float | None
    coverage: float  # fraction of selected tickers with prices
    net_return: float | None = None
    volatility: float | None = None
    max_drawdown: float | None = None
    hit_rate: float | None = None
    sector_neutral: bool = False
    static_seed_share: float | None = None


@dataclass(frozen=True)
class UniverseRow:
    """Typed view of one universe CSV row."""

    ticker: str
    exchange: str
    name: str
    segment: str
    subsegment: str | None
    exposure_pct: float
    mcap_usd: float


_MIN_SCORE_FOR_BASKET = 50.0
_SEGMENT_SCORE_PROXIMITY = 10.0
_MIN_EXPOSURE_PCT = 50.0
_MIN_MARKET_CAP_USD = 2_000_000_000.0
_MAX_LONG_SEGMENTS = 2
_MAX_SHORT_SEGMENTS = 2
_MIN_LONG_TICKERS = 3
_MAX_LONG_TICKERS = 5
_MIN_SHORT_TICKERS = 3
_MAX_SHORT_TICKERS = 5
_TX_COST_PER_TRADE = 0.001  # 10 bps per position on entry


def _load_universe(path: Path) -> list[UniverseRow]:
    """Read the universe CSV and return typed rows."""
    if not path.exists():
        return []
    out: list[UniverseRow] = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                exposure = float(row.get("exposure_pct") or 0) / 100.0
                mcap = float(row.get("mcap_usd") or 0)
            except (TypeError, ValueError):
                continue
            out.append(
                UniverseRow(
                    ticker=(row.get("ticker") or "").strip(),
                    exchange=(row.get("exchange") or "").strip(),
                    name=(row.get("name") or "").strip(),
                    segment=(row.get("segment") or "").strip(),
                    subsegment=(row.get("subsegment") or "").strip() or None,
                    exposure_pct=exposure,
                    mcap_usd=mcap,
                )
            )
    return out


def _eligible_tickers(
    rows: list[UniverseRow],
    segment: str,
    score: float,
) -> list[UniverseRow]:
    """Filter universe rows for basket inclusion."""
    return [
        r
        for r in rows
        if r.segment == segment
        and r.exposure_pct >= _MIN_EXPOSURE_PCT / 100.0
        and r.mcap_usd >= _MIN_MARKET_CAP_USD
        and r.ticker
        and r.name
    ]


def _select_top_segments(
    scores: dict[str, dict[str, Any]],
    side: str,
) -> list[str]:
    """Select top segments for the basket per methodology §7.9.

    Long: highest B, excluding hard-guard regimes.
    Short: RESOLVING with B >= 50, ranked by B * abs(B').
    """
    if side == "long":
        candidates = []
        for seg, data in scores.items():
            if data.get("b", 0.0) < _MIN_SCORE_FOR_BASKET:
                continue
            regime = data.get("regime")
            if regime in (Regime.RESOLVING, Regime.RESOLVING_FROM_LOW, Regime.NO_DATA):
                continue
            candidates.append((seg, data["b"], data.get("momentum", 0.0)))
        candidates.sort(key=lambda t: (t[1], t[2]), reverse=True)
        selected = [seg for seg, _, _ in candidates[:_MAX_LONG_SEGMENTS]]
        # Include a second segment only if it is within 10 points of the top.
        if len(selected) == 2 and candidates:
            top_score = candidates[0][1]
            if candidates[1][1] < top_score - _SEGMENT_SCORE_PROXIMITY:
                selected = selected[:1]
        return selected

    if side == "short":
        candidates = []
        for seg, data in scores.items():
            if data.get("b", 0.0) < _MIN_SCORE_FOR_BASKET:
                continue
            regime = data.get("regime")
            if regime != Regime.RESOLVING:
                continue
            score = data["b"] * abs(data.get("momentum", 0.0))
            candidates.append((seg, score, data["b"]))
        candidates.sort(key=lambda t: (t[1], t[2]), reverse=True)
        selected = [seg for seg, _, _ in candidates[:_MAX_SHORT_SEGMENTS]]
        # Include a second segment only if it is within proximity of the top combined score.
        if len(selected) == 2 and candidates:
            top_score = candidates[0][1]
            if candidates[1][1] < top_score - _SEGMENT_SCORE_PROXIMITY:
                selected = selected[:1]
        return selected

    return []


def _find_close_on_or_before(
    bars: list[tuple[date, float]],
    t: date,
) -> tuple[date, float] | None:
    """Most recent bar at or before `t`."""
    chosen: tuple[date, float] | None = None
    for d, c in bars:
        if d <= t:
            chosen = (d, c)
        else:
            break
    return chosen


def _ticker_forward_return(
    bars: list[tuple[date, float]],
    t: date,
    forward_days: int,
) -> float | None:
    """Equal to the CsvPriceProvider forward return logic."""
    start_bar = _find_close_on_or_before(bars, t)
    if start_bar is None or start_bar[1] <= 0:
        return None
    target = t + __import__("datetime").timedelta(days=forward_days)
    end_bar: tuple[date, float] | None = None
    for d, c in bars:
        if d <= target:
            end_bar = (d, c)
        else:
            break
    if end_bar is None or end_bar[0] == start_bar[0]:
        return None
    return (end_bar[1] - start_bar[1]) / start_bar[1]


def _portfolio_max_drawdown(
    bars_list: list[list[tuple[date, float]]],
    weights: list[float],
    eval_date: date,
    forward_days: int,
) -> float | None:
    """Max drawdown of a weighted portfolio over the forward window."""
    if not bars_list or not weights or len(bars_list) != len(weights):
        return None

    start_closes: list[float] = []
    for bars in bars_list:
        start_bar = _find_close_on_or_before(bars, eval_date)
        if start_bar is None or start_bar[1] <= 0:
            return None
        start_closes.append(start_bar[1])

    end_date = eval_date + __import__("datetime").timedelta(days=forward_days)
    maps: list[dict[date, float]] = []
    for bars in bars_list:
        d: dict[date, float] = {}
        for bd, bc in bars:
            if eval_date <= bd <= end_date:
                d[bd] = bc
        maps.append(d)

    common_dates = sorted(set(maps[0]).intersection(*[set(m) for m in maps[1:]])) if maps else []
    if len(common_dates) < 2:
        return None

    peak: float | None = None
    max_dd = 0.0
    for dt in common_dates:
        value = sum(weights[i] * (maps[i][dt] / start_closes[i]) for i in range(len(bars_list)))
        if peak is None or value > peak:
            peak = value
        dd = value / peak - 1
        if dd < max_dd:
            max_dd = dd
    return max_dd


def _entry_weights(
    entries: list[TickerBasketEntry],
    selected_segments: list[str],
    sector_neutral: bool,
) -> dict[str, float]:
    """Return ticker -> target weight.

    Equal-weight by default. When ``sector_neutral`` is true, each selected
    segment receives equal total weight and tickers within a segment are
    equal-weighted.
    """
    if not entries:
        return {}
    if sector_neutral:
        by_segment: dict[str, list[TickerBasketEntry]] = {}
        for entry in entries:
            by_segment.setdefault(entry.segment, []).append(entry)
        weights: dict[str, float] = {}
        for group in by_segment.values():
            seg_weight = 1.0 / len(by_segment)
            for entry in group:
                weights[entry.ticker] = seg_weight / len(group)
        return weights
    weight = 1.0 / len(entries)
    return {entry.ticker: weight for entry in entries}


def _basket_metrics(
    entries: list[TickerBasketEntry],
    prices: dict[str, list[tuple[date, float]]],
    eval_date: date,
    forward_days: int,
) -> tuple[float | None, float | None, float | None, float | None, float | None, float]:
    """Compute gross return, net return, volatility, max drawdown, hit rate, coverage."""
    if not entries or forward_days <= 0:
        return None, None, None, None, None, 0.0

    returns: dict[str, float] = {}
    for entry in entries:
        r = _ticker_forward_return(prices.get(entry.ticker, []), eval_date, forward_days)
        if r is not None:
            returns[entry.ticker] = r

    coverage = len(returns) / len(entries)
    if not returns:
        return None, None, None, None, None, coverage

    weights = {entry.ticker: entry.weight for entry in entries}
    available_weights = {ticker: weights[ticker] for ticker in returns}
    total_w = sum(available_weights.values())
    if total_w <= 0:
        return None, None, None, None, None, coverage
    norm = {ticker: w / total_w for ticker, w in available_weights.items()}

    gross = sum(norm[ticker] * ret for ticker, ret in returns.items())
    net = gross - _TX_COST_PER_TRADE * len(entries)

    rets = list(returns.values())
    hit_rate = sum(1 for r in rets if r > 0) / len(rets)

    if len(rets) >= 2:
        vol = statistics.stdev(rets) * math.sqrt(252.0 / forward_days)
    else:
        vol = None

    bars_list = [prices.get(ticker, []) for ticker in returns]
    md = _portfolio_max_drawdown(
        bars_list,
        [norm[ticker] for ticker in returns],
        eval_date,
        forward_days,
    )

    return gross, net, vol, md, hit_rate, coverage


def _build_basket(
    side: str,
    eval_date: date,
    horizon: str,
    selected_segments: list[str],
    universe_rows: list[UniverseRow],
    scores: dict[str, dict[str, Any]],
    prices: dict[str, list[tuple[date, float]]],
    forward_days: int,
    sector_neutral: bool = False,
) -> Basket:
    """Construct one basket and compute its equal-weight forward return."""
    entries: list[TickerBasketEntry] = []
    for segment in selected_segments:
        score = scores.get(segment, {}).get("b", 0.0)
        eligible = _eligible_tickers(universe_rows, segment, score)
        eligible.sort(key=lambda r: r.exposure_pct * score, reverse=True)
        max_tickers = _MAX_LONG_TICKERS if side == "long" else _MAX_SHORT_TICKERS
        min_tickers = _MIN_LONG_TICKERS if side == "long" else _MIN_SHORT_TICKERS
        chosen = eligible[:max_tickers]
        if len(chosen) < min_tickers:
            # Not enough liquid tickers; still include what we have.
            pass
        for row in chosen:
            entries.append(
                TickerBasketEntry(
                    ticker=row.ticker,
                    name=row.name,
                    segment=row.segment,
                    exposure_pct=row.exposure_pct,
                    mcap_usd=row.mcap_usd,
                    score=score,
                    score_contribution=row.exposure_pct * score,
                )
            )

    # Deduplicate by ticker across segments; keep the highest contribution.
    by_ticker: dict[str, TickerBasketEntry] = {}
    for entry in entries:
        existing = by_ticker.get(entry.ticker)
        if existing is None or entry.score_contribution > existing.score_contribution:
            by_ticker[entry.ticker] = entry
    unique_entries = list(by_ticker.values())

    weights = _entry_weights(unique_entries, selected_segments, sector_neutral)
    weighted_entries = [replace(entry, weight=weights.get(entry.ticker, 1.0)) for entry in unique_entries]

    gross, net, vol, md, hit_rate, coverage = _basket_metrics(weighted_entries, prices, eval_date, forward_days)

    return Basket(
        side=side,
        eval_date=eval_date,
        horizon=horizon,
        segments=selected_segments,
        tickers=weighted_entries,
        equal_weight_return=gross,
        net_return=net,
        volatility=vol,
        max_drawdown=md,
        hit_rate=hit_rate,
        coverage=coverage,
        sector_neutral=sector_neutral,
    )


def _build_watchlist(
    eval_date: date,
    horizon: str,
    scores: dict[str, dict[str, Any]],
    universe_rows: list[UniverseRow],
    prices: dict[str, list[tuple[date, float]]] | None = None,
    forward_days: int = 0,
) -> Basket:
    """Build a watchlist of EMERGING + PEAKED tickers with B >= 50."""
    selected = [
        seg
        for seg, data in scores.items()
        if data.get("b", 0.0) >= _MIN_SCORE_FOR_BASKET and data.get("regime") in (Regime.EMERGING, Regime.PEAKED)
    ]
    selected.sort(key=lambda seg: scores[seg]["b"], reverse=True)
    selected = selected[:_MAX_LONG_SEGMENTS]

    entries: list[TickerBasketEntry] = []
    for segment in selected:
        score = scores.get(segment, {}).get("b", 0.0)
        eligible = _eligible_tickers(universe_rows, segment, score)
        eligible.sort(key=lambda r: r.exposure_pct * score, reverse=True)
        for row in eligible[:_MAX_LONG_TICKERS]:
            entries.append(
                TickerBasketEntry(
                    ticker=row.ticker,
                    name=row.name,
                    segment=row.segment,
                    exposure_pct=row.exposure_pct,
                    mcap_usd=row.mcap_usd,
                    score=score,
                    score_contribution=row.exposure_pct * score,
                )
            )

    by_ticker: dict[str, TickerBasketEntry] = {}
    for entry in entries:
        existing = by_ticker.get(entry.ticker)
        if existing is None or entry.score_contribution > existing.score_contribution:
            by_ticker[entry.ticker] = entry
    unique_entries = list(by_ticker.values())

    if prices is not None and forward_days > 0:
        weights = _entry_weights(unique_entries, selected, False)
        weighted_entries = [replace(entry, weight=weights.get(entry.ticker, 1.0)) for entry in unique_entries]
        _, net, vol, md, hit_rate, coverage = _basket_metrics(weighted_entries, prices, eval_date, forward_days)
    else:
        weighted_entries = unique_entries
        net = vol = md = hit_rate = None
        coverage = 0.0

    return Basket(
        side="watchlist",
        eval_date=eval_date,
        horizon=horizon,
        segments=selected,
        tickers=weighted_entries,
        equal_weight_return=None,
        net_return=net,
        volatility=vol,
        max_drawdown=md,
        hit_rate=hit_rate,
        coverage=coverage,
    )


def build_baskets(
    *,
    eval_date: date,
    horizon: str,
    scores: dict[str, dict[str, Any]],
    universe_path: Path,
    prices: dict[str, list[tuple[date, float]]],
    forward_days: int,
    sector_neutral: bool = False,
) -> dict[str, Basket]:
    """Build long, short, and watchlist baskets for one evaluation date.

    Args:
        eval_date: the as-of date for the basket.
        horizon: one of "near", "med", "long".
        scores: dict segment -> {"b": float, "momentum": float, "regime": Regime}.
        universe_path: path to the universe CSV.
        prices: dict ticker -> list of (date, close) sorted ascending.
        forward_days: forward return horizon for long/short baskets.
        sector_neutral: when True, allocate equal total weight to each
            selected segment instead of equal weighting across tickers.

    Returns:
        dict keyed by "long", "short", "watchlist".
    """
    universe_rows = _load_universe(universe_path)
    long_segments = _select_top_segments(scores, "long")
    short_segments = _select_top_segments(scores, "short")
    return {
        "long": _build_basket(
            "long",
            eval_date,
            horizon,
            long_segments,
            universe_rows,
            scores,
            prices,
            forward_days,
            sector_neutral=sector_neutral,
        ),
        "short": _build_basket(
            "short",
            eval_date,
            horizon,
            short_segments,
            universe_rows,
            scores,
            prices,
            forward_days,
            sector_neutral=sector_neutral,
        ),
        "watchlist": _build_watchlist(
            eval_date,
            horizon,
            scores,
            universe_rows,
            prices=prices,
            forward_days=forward_days,
        ),
    }
