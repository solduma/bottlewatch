"""Ticker-level conviction basket engine (methodology §7.9).

Builds long, short, and watchlist baskets at each evaluation date from
segment scores and the universe CSV.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
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


def _build_basket(
    side: str,
    eval_date: date,
    horizon: str,
    selected_segments: list[str],
    universe_rows: list[UniverseRow],
    scores: dict[str, dict[str, Any]],
    prices: dict[str, list[tuple[date, float]]],
    forward_days: int,
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

    returns: list[float] = []
    for entry in unique_entries:
        r = _ticker_forward_return(prices.get(entry.ticker, []), eval_date, forward_days)
        if r is not None:
            returns.append(r)

    equal_weight_return = sum(returns) / len(returns) if returns else None
    coverage = len(returns) / len(unique_entries) if unique_entries else 0.0

    return Basket(
        side=side,
        eval_date=eval_date,
        horizon=horizon,
        segments=selected_segments,
        tickers=unique_entries,
        equal_weight_return=equal_weight_return,
        coverage=coverage,
    )


def _build_watchlist(
    eval_date: date,
    horizon: str,
    scores: dict[str, dict[str, Any]],
    universe_rows: list[UniverseRow],
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

    return Basket(
        side="watchlist",
        eval_date=eval_date,
        horizon=horizon,
        segments=selected,
        tickers=unique_entries,
        equal_weight_return=None,
        coverage=0.0,
    )


def _ticker_forward_return(
    bars: list[tuple[date, float]],
    t: date,
    forward_days: int,
) -> float | None:
    """Equal to the CsvPriceProvider forward return logic."""
    start_bar: tuple[date, float] | None = None
    for d, c in bars:
        if d <= t:
            start_bar = (d, c)
        else:
            break
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


def build_baskets(
    *,
    eval_date: date,
    horizon: str,
    scores: dict[str, dict[str, Any]],
    universe_path: Path,
    prices: dict[str, list[tuple[date, float]]],
    forward_days: int,
) -> dict[str, Basket]:
    """Build long, short, and watchlist baskets for one evaluation date.

    Args:
        eval_date: the as-of date for the basket.
        horizon: one of "near", "med", "long".
        scores: dict segment -> {"b": float, "momentum": float, "regime": Regime}.
        universe_path: path to the universe CSV.
        prices: dict ticker -> list of (date, close) sorted ascending.
        forward_days: forward return horizon for long/short baskets.

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
        ),
        "watchlist": _build_watchlist(eval_date, horizon, scores, universe_rows),
    }
