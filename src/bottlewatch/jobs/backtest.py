"""Walk-forward backtest of score_history vs ticker returns.

Methodology (m4-backtest-initial.md "Next Steps" item 3):

For each evaluation date t in the requested window:
    For each (ticker, segment) pair in the universe:
        B(t) = the score_history row for (segment, horizon, computed_at <= t)
        R(t) = forward return over `--forward-days` trading days:
               (close[t + N] - close[t]) / close[t]
        If either is missing, skip this tuple.

Aggregations:
    per_segment    Spearman(B, R) pooled over all (ticker, t) within one segment
    per_eval_date  Spearman(B, R) across all (ticker, segment) at one date t
    overall        Spearman(B, R) across all (ticker, segment, t) tuples

The job is pure compute over (score_history rows + universe CSV +
price CSV). No network, no DB writes.

CLI:
    bottlewatch-backtest --prices data/processed/prices.csv \
                         --start 2024-06-01 --end 2026-06-01 \
                         --forward-days 90 --horizon near
"""

from __future__ import annotations

import argparse
import csv as _csv
import json
import logging
import math
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from bottlewatch.app.backtest.prices import CsvPriceProvider, PriceBar, PriceProvider
from bottlewatch.app.db import ScoreHistory, make_engine, make_session_factory

_LOGGER = logging.getLogger(__name__)

# Project root: src/bottlewatch/jobs/backtest.py -> ../../../
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_UNIVERSE = _PROJECT_ROOT / "research" / "02_universe.csv"
_DEFAULT_PRICES = _PROJECT_ROOT / "data" / "processed" / "prices.csv"


# ---------------------------------------------------------------------------
# Pure math: Spearman rank correlation with two-sided p-value
# ---------------------------------------------------------------------------


def _rank(xs: list[float]) -> list[float]:
    """Average ranks for ties (Spearman's "fractional" tie-breaking)."""
    n = len(xs)
    indexed = sorted(enumerate(xs), key=lambda t: t[1])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and indexed[j + 1][1] == indexed[i][1]:
            j += 1
        # Average rank for the run [i..j] (1-indexed).
        avg = (i + 1 + j + 1) / 2.0
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg
        i = j + 1
    return ranks


def spearman(x: list[float], y: list[float]) -> tuple[float | None, float | None]:
    """Spearman's rho and a two-sided p-value (t-distribution approximation).

    Pure-Python. Returns (None, None) when n < 2 or when x and y
    have zero variance (no signal). The p-value is a Student-t
    approximation valid for n >= 4; for n < 4 we return None and
    the caller treats the result as "insufficient data".
    """
    n = len(x)
    if n != len(y):
        raise ValueError("x and y must have the same length")
    if n < 2:
        return None, None
    if len(set(x)) < 2 or len(set(y)) < 2:
        return None, None
    rx = _rank(x)
    ry = _rank(y)
    mx = sum(rx) / n
    my = sum(ry) / n
    sxx = sum((r - mx) ** 2 for r in rx)
    syy = sum((r - my) ** 2 for r in ry)
    if sxx == 0 or syy == 0:
        return None, None
    sxy = sum((rx[i] - mx) * (ry[i] - my) for i in range(n))
    rho = sxy / math.sqrt(sxx * syy)
    if n < 4:
        return rho, None
    # Two-sided p-value via Student-t with df = n - 2. scipy is not
    # a dependency, so we approximate the survival function using
    # the regularized incomplete beta function. For df >= 2, the
    # t-distribution CDF is 0.5 + t * gamma((df+1)/2) * 1F1(...) / ...
    # — too messy. We use the standard approximation: convert to
    # z = rho * sqrt((n-2) / (1 - rho^2)), then a normal-approx
    # two-sided p. This is what `cor.test` in R does when `exact=FALSE`.
    r2 = rho * rho
    if r2 >= 1.0:
        return rho, 0.0
    t_stat = rho * math.sqrt((n - 2) / (1.0 - r2))
    # erfc-based normal CDF: p = erfc(|t| / sqrt(2))
    p = _erfc_two_sided(t_stat)
    return rho, p


def _erfc_two_sided(t: float) -> float:
    """Two-sided p-value from a t-statistic using a normal approximation.

    The exact Student-t survival function is not available without
    scipy; for the backtest's purposes a normal approximation is
    adequate (n is typically in the dozens, and we're reporting
    a heuristic p, not a hypothesis test result).
    """
    return math.erfc(abs(t) / math.sqrt(2.0))


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvalPoint:
    """One (ticker, segment, t) triple in the backtest."""

    ticker: str
    segment: str
    eval_date: date
    b: float
    forward_return: float


@dataclass(frozen=True)
class SegmentResult:
    segment: str
    n: int
    rho: float | None
    p_value: float | None


@dataclass(frozen=True)
class EvalDateResult:
    date: date
    n: int
    rho: float | None
    p_value: float | None


@dataclass(frozen=True)
class OverallResult:
    n: int
    rho: float | None
    p_value: float | None


@dataclass
class BacktestReport:
    horizon: str
    forward_days: int
    n_eval_dates: int
    n_eval_points: int
    per_segment: list[SegmentResult]
    per_eval_date: list[EvalDateResult]
    overall: OverallResult

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "horizon": self.horizon,
            "forward_days": self.forward_days,
            "n_eval_dates": self.n_eval_dates,
            "n_eval_points": self.n_eval_points,
            "per_segment": [asdict(s) for s in self.per_segment],
            "per_eval_date": [asdict(d) for d in self.per_eval_date],
            "overall": asdict(self.overall),
        }


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------


def _load_universe(path: Path) -> list[tuple[str, str]]:
    """Read the universe CSV. Returns [(ticker, segment), ...]."""
    if not path.exists():
        _LOGGER.warning("universe CSV missing at %s", path)
        return []
    out: list[tuple[str, str]] = []
    with path.open(newline="", encoding="utf-8") as fh:
        for row in _csv.DictReader(fh):
            t = (row.get("ticker") or "").strip()
            s = (row.get("segment") or "").strip()
            if t and s:
                out.append((t, s))
    return out


def _load_score_history(
    factory: sessionmaker,
    segment: str,
    horizon: str,
    until: date,
) -> list[tuple[datetime, float]]:
    """Return [(computed_at, b), ...] for (segment, horizon) up to `until`, sorted ascending."""
    with factory() as session:
        rows = session.execute(
            select(ScoreHistory.computed_at, ScoreHistory.b)
            .where(
                ScoreHistory.segment == segment,
                ScoreHistory.horizon == horizon,
                ScoreHistory.computed_at <= datetime.combine(until, datetime.min.time()),
            )
            .order_by(ScoreHistory.computed_at.asc())
        ).all()
    return [(r[0], r[1]) for r in rows if r[1] is not None]


def _b_at(b_series: list[tuple[datetime, float]], t: date) -> float | None:
    """Most recent B for (segment, horizon) at or before date t."""
    target = datetime.combine(t, datetime.min.time())
    latest: float | None = None
    for ts, b in b_series:
        if ts <= target:
            latest = b
        else:
            break
    return latest


def _find_close(bars: list[PriceBar], on_or_before: date) -> PriceBar | None:
    """The most recent close at or before `on_or_before`."""
    bar: PriceBar | None = None
    for b in bars:
        if b.date <= on_or_before:
            bar = b
        else:
            break
    return bar


def _forward_return(bars: list[PriceBar], t: date, forward_days: int) -> float | None:
    """(close[t + N] - close[t]) / close[t]. Returns None when either
    boundary is missing or when the close at t + N is the same bar
    as the close at t (no price progress over the forward window —
    happens when the only bar available is the one at t).
    """
    t_bar = _find_close(bars, t)
    if t_bar is None or t_bar.close <= 0:
        return None
    t_plus = t + timedelta(days=forward_days)
    t_plus_bar = _find_close(bars, t_plus)
    if t_plus_bar is None or t_plus_bar.date == t_bar.date:
        return None
    return (t_plus_bar.close - t_bar.close) / t_bar.close


def _eval_dates(start: date, end: date, step_days: int = 30) -> list[date]:
    """Generate monthly evaluation dates from start to end inclusive."""
    if end < start:
        return []
    out: list[date] = []
    current = start
    while current <= end:
        out.append(current)
        current = current + timedelta(days=step_days)
    return out


def run_backtest(
    *,
    prices: PriceProvider,
    factory: sessionmaker,
    universe_path: Path = _DEFAULT_UNIVERSE,
    start: date,
    end: date,
    forward_days: int = 90,
    horizon: str = "near",
) -> BacktestReport:
    """Compute the walk-forward correlations.

    The function is pure compute over the inputs. No side effects.
    """
    universe = _load_universe(universe_path)
    eval_dates = _eval_dates(start, end)
    if not universe or not eval_dates:
        return BacktestReport(
            horizon=horizon,
            forward_days=forward_days,
            n_eval_dates=0,
            n_eval_points=0,
            per_segment=[],
            per_eval_date=[],
            overall=OverallResult(n=0, rho=None, p_value=None),
        )

    # Pre-load score_history per segment (small, ~30 rows per segment).
    b_by_segment: dict[str, list[tuple[datetime, float]]] = {}
    for _, seg in universe:
        if seg not in b_by_segment:
            b_by_segment[seg] = _load_score_history(factory, seg, horizon, end)

    # Pre-load price bars per ticker (cache once per ticker for the
    # whole window so we don't re-read the CSV 12 times).
    bars_by_ticker: dict[str, list[PriceBar]] = {}
    for ticker, _ in universe:
        if ticker not in bars_by_ticker:
            bars_by_ticker[ticker] = prices.get_prices(ticker, start, end + timedelta(days=forward_days))

    # Walk forward.
    eval_points: list[EvalPoint] = []
    for t in eval_dates:
        for ticker, seg in universe:
            b_series = b_by_segment.get(seg, [])
            b = _b_at(b_series, t)
            if b is None:
                continue
            bars = bars_by_ticker.get(ticker, [])
            r = _forward_return(bars, t, forward_days)
            if r is None:
                continue
            eval_points.append(EvalPoint(ticker, seg, t, b, r))

    # Per-segment Spearman.
    per_segment_results: list[SegmentResult] = []
    segments_in_data = sorted({p.segment for p in eval_points})
    for seg in segments_in_data:
        seg_points = [p for p in eval_points if p.segment == seg]
        xs = [p.b for p in seg_points]
        ys = [p.forward_return for p in seg_points]
        rho, p_val = spearman(xs, ys)
        per_segment_results.append(SegmentResult(seg, len(seg_points), rho, p_val))

    # Per-eval-date Spearman.
    per_eval_date_results: list[EvalDateResult] = []
    for t in eval_dates:
        t_points = [p for p in eval_points if p.eval_date == t]
        xs = [p.b for p in t_points]
        ys = [p.forward_return for p in t_points]
        rho, p_val = spearman(xs, ys)
        per_eval_date_results.append(EvalDateResult(t, len(t_points), rho, p_val))

    # Overall.
    xs = [p.b for p in eval_points]
    ys = [p.forward_return for p in eval_points]
    rho, p_val = spearman(xs, ys)
    overall = OverallResult(len(eval_points), rho, p_val)

    return BacktestReport(
        horizon=horizon,
        forward_days=forward_days,
        n_eval_dates=len(eval_dates),
        n_eval_points=len(eval_points),
        per_segment=per_segment_results,
        per_eval_date=per_eval_date_results,
        overall=overall,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="bottlewatch-backtest",
        description="Walk-forward backtest of score_history vs ticker returns.",
    )
    parser.add_argument(
        "--prices",
        type=Path,
        default=_DEFAULT_PRICES,
        help="Path to prices.csv (ticker,date,close). Default: data/processed/prices.csv.",
    )
    parser.add_argument(
        "--universe",
        type=Path,
        default=_DEFAULT_UNIVERSE,
        help="Path to the ticker universe CSV. Default: research/02_universe.csv.",
    )
    parser.add_argument("--start", type=date.fromisoformat, default=None, help="First eval date (YYYY-MM-DD).")
    parser.add_argument("--end", type=date.fromisoformat, default=None, help="Last eval date (YYYY-MM-DD).")
    parser.add_argument(
        "--forward-days", type=int, default=90, help="Forward return window in calendar days. Default: 90."
    )
    parser.add_argument("--horizon", choices=("near", "med", "long"), default="near", help="Score horizon to evaluate.")
    parser.add_argument("--output", type=Path, default=None, help="Write JSON report here. Default: stdout.")
    parser.add_argument(
        "--database-url",
        type=str,
        default=None,
        help="Override the database URL. Default: from settings.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    today = date.today()
    start = args.start or (today - timedelta(days=180))
    end = args.end or today
    if start > end:
        print(f"error: --start {start} is after --end {end}", file=sys.stderr)
        return 2

    if args.database_url:
        factory = make_session_factory(make_engine(args.database_url))
    else:
        from bottlewatch.config import get_settings

        factory = make_session_factory(make_engine(get_settings().database_url))

    prices = CsvPriceProvider(args.prices)
    report = run_backtest(
        prices=prices,
        factory=factory,
        universe_path=args.universe,
        start=start,
        end=end,
        forward_days=args.forward_days,
        horizon=args.horizon,
    )
    payload = report.to_jsonable()
    text = json.dumps(payload, indent=2, default=str)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
