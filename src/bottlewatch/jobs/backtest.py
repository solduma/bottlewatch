"""Walk-forward backtest of bottleneck scores vs ticker returns.

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
import sys
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from scipy import stats
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from bottlewatch.app.backtest.basket_report import BacktestReport, BasketSnapshot, SegmentICRow
from bottlewatch.app.backtest.baskets import build_baskets
from bottlewatch.app.backtest.prices import CsvPriceProvider, PriceBar, PriceProvider
from bottlewatch.app.backtest.stats import SegmentICResult, benjamini_hochberg, segment_ic_with_ci
from bottlewatch.app.db import ScoreHistory, make_engine, make_session_factory
from bottlewatch.app.score.regime import Regime, regime_from_value
from bottlewatch.config import get_settings

_LOGGER = logging.getLogger(__name__)

# Project root: src/bottlewatch/jobs/backtest.py -> ../../../
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_UNIVERSE = _PROJECT_ROOT / "research" / "02_universe.csv"
_DEFAULT_PRICES = _PROJECT_ROOT / "data" / "processed" / "prices.csv"


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
    regime: str


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
    normalization_mode: str,
) -> list[tuple[datetime, float, float, str]]:
    """Return [(computed_at, b, momentum, regime), ...] for (segment, horizon) up to `until`, sorted ascending."""
    with factory() as session:
        rows = session.execute(
            select(ScoreHistory.computed_at, ScoreHistory.b, ScoreHistory.momentum, ScoreHistory.regime)
            .where(
                ScoreHistory.segment == segment,
                ScoreHistory.horizon == horizon,
                ScoreHistory.computed_at <= datetime.combine(until, datetime.min.time()),
                (
                    (ScoreHistory.normalization_mode == normalization_mode)
                    | ((ScoreHistory.normalization_mode.is_(None)) & (normalization_mode == "fixed"))
                ),
            )
            .order_by(ScoreHistory.computed_at.asc())
        ).all()
    return [(r[0], r[1], r[2] or 0.0, r[3]) for r in rows if r[1] is not None]


def _b_at(b_series: list[tuple[datetime, float, float, str]], t: date) -> tuple[float, float, str] | None:
    """Most recent B, momentum, and regime for (segment, horizon) at or before date t."""
    target = datetime.combine(t, datetime.min.time())
    latest: tuple[float, float, str] | None = None
    for ts, b, momentum, regime in b_series:
        if ts <= target:
            latest = (b, momentum, regime)
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


def _compute_ic(xs: list[float], ys: list[float]) -> tuple[float | None, float | None]:
    """Spearman rho and two-sided p-value via scipy."""
    n = len(xs)
    if n < 4 or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None, None
    spearman_result: Any = stats.spearmanr(xs, ys)
    return float(spearman_result.statistic), float(
        spearman_result.pvalue
    ) if spearman_result.pvalue is not None else None


def _run_single_mode(
    *,
    prices: PriceProvider,
    factory: sessionmaker,
    universe_path: Path,
    start: date,
    end: date,
    forward_days: int,
    horizon: str,
    normalization_mode: str,
) -> tuple[BacktestReport, list[EvalPoint]]:
    """Run the backtest for one normalization mode.

    This reads the materialized `score_history` table. The caller is
    responsible for ensuring the table contains the right normalization
    mode (e.g., by running a point-in-time recompute beforehand).
    """
    universe = _load_universe(universe_path)
    eval_dates = _eval_dates(start, end)
    if not universe or not eval_dates:
        return (
            BacktestReport(
                horizon=horizon,
                forward_days=forward_days,
                start=start,
                end=end,
                normalization_mode=normalization_mode,
                n_eval_dates=0,
                n_eval_points=0,
                overall_ic=None,
                overall_p_value=None,
                per_segment_ic=[],
                baskets=[],
                fixed_vs_rolling=None,
                seed_share_warning_dates=[],
            ),
            [],
        )

    # Pre-load score_history per segment.
    b_by_segment: dict[str, list[tuple[datetime, float, float, str]]] = {}
    for _, seg in universe:
        if seg not in b_by_segment:
            b_by_segment[seg] = _load_score_history(factory, seg, horizon, end, normalization_mode)

    # Pre-load price bars per ticker.
    bars_by_ticker: dict[str, list[PriceBar]] = {}
    for ticker, _ in universe:
        if ticker not in bars_by_ticker:
            bars_by_ticker[ticker] = prices.get_prices(ticker, start, end + timedelta(days=forward_days))

    # Walk forward for IC and baskets.
    eval_points: list[EvalPoint] = []
    basket_snapshots: list[BasketSnapshot] = []
    seed_share_warning_dates: list[date] = []
    for t in eval_dates:
        # Build baskets per segment scores at t.
        segment_scores: dict[str, dict[str, Any]] = {}
        for _, seg in universe:
            row = _b_at(b_by_segment.get(seg, []), t)
            if row is None:
                continue
            b, momentum, regime_str = row
            segment_scores[seg] = {
                "b": b,
                "momentum": momentum,
                "regime": regime_from_value(regime_str),
            }

        # Baskets use the same price provider but indexed by ticker.
        ticker_prices: dict[str, list[tuple[date, float]]] = {
            ticker: [(b.date, b.close) for b in bars] for ticker, bars in bars_by_ticker.items()
        }
        baskets = build_baskets(
            eval_date=t,
            horizon=horizon,
            scores=segment_scores,
            universe_path=universe_path,
            prices=ticker_prices,
            forward_days=forward_days,
        )
        for side, basket in baskets.items():
            basket_snapshots.append(
                BasketSnapshot(
                    eval_date=t,
                    side=side,
                    segments=basket.segments,
                    tickers=[e.ticker for e in basket.tickers],
                    weights={e.ticker: e.weight for e in basket.tickers},
                    equal_weight_return=basket.equal_weight_return,
                    net_return=basket.net_return,
                    volatility=basket.volatility,
                    max_drawdown=basket.max_drawdown,
                    hit_rate=basket.hit_rate,
                    coverage=basket.coverage,
                    sector_neutral=basket.sector_neutral,
                )
            )

        # Seed-share warning: if the average static_seed_share across
        # segments is > 0.80, flag the date. We don't have static_seed_share
        # in score_history, so we use a simple proxy: if >50% of segments
        # lack a dynamic score (no live source), warn.
        total_segments = len(segment_scores)
        live_segments = sum(
            1
            for data in segment_scores.values()
            if data.get("regime") not in (Regime.NO_DATA,) and data["b"] is not None
        )
        if total_segments > 0 and live_segments / total_segments < 0.20:
            seed_share_warning_dates.append(t)

        # Ticker-level eval points for IC.
        for ticker, seg in universe:
            row = _b_at(b_by_segment.get(seg, []), t)
            if row is None:
                continue
            b = row[0]
            regime = row[2]
            bars = bars_by_ticker.get(ticker, [])
            r = _forward_return(bars, t, forward_days)
            if r is None:
                continue
            eval_points.append(EvalPoint(ticker, seg, t, b, r, regime))

    # Per-segment IC with block-bootstrap CI and BH correction.
    per_segment_raw: list[SegmentICResult] = []
    segments_in_data = sorted({p.segment for p in eval_points})
    p_values_for_bh: list[tuple[str, float | None]] = []
    constant_score_segments: set[str] = set()
    for seg in segments_in_data:
        seg_points = [p for p in eval_points if p.segment == seg]
        xs = [p.b for p in seg_points]
        ys = [p.forward_return for p in seg_points]
        if len(set(xs)) < 2:
            # A constant score across the entire backtest window means
            # no statistical relationship can be measured. This happens
            # when the historical recompute pipeline used static seeds
            # with no time-varying dynamic inputs.
            constant_score_segments.add(seg)
            p_values_for_bh.append((seg, None))
            per_segment_raw.append(
                SegmentICResult(
                    segment=seg,
                    n=len(seg_points),
                    rho=None,
                    p_value=None,
                    ci_low=None,
                    ci_high=None,
                    bh_rejected=False,
                )
            )
            continue
        points_by_date: dict[date, list[tuple[float, float]]] = {}
        for p in seg_points:
            points_by_date.setdefault(p.eval_date, []).append((p.b, p.forward_return))
        result = segment_ic_with_ci(seg, xs, ys, eval_dates, points_by_date)
        p_values_for_bh.append((seg, result.p_value))
        per_segment_raw.append(result)

    bh_results = benjamini_hochberg(p_values_for_bh, alpha=0.10)
    per_segment_results: list[SegmentICRow] = [
        SegmentICRow(
            segment=r.segment,
            n=r.n,
            rho=r.rho,
            p_value=r.p_value,
            ci_low=r.ci_low,
            ci_high=r.ci_high,
            bh_rejected=bh_results.get(r.segment, False),
        )
        for r in per_segment_raw
    ]
    if constant_score_segments:
        _LOGGER.warning(
            "%d segments had constant scores over the backtest window (no IC computable): %s",
            len(constant_score_segments),
            ", ".join(sorted(constant_score_segments)[:10]) + ("..." if len(constant_score_segments) > 10 else ""),
        )

    # Overall IC.
    xs = [p.b for p in eval_points]
    ys = [p.forward_return for p in eval_points]
    overall_ic, overall_p = _compute_ic(xs, ys)

    report = BacktestReport(
        horizon=horizon,
        forward_days=forward_days,
        start=start,
        end=end,
        normalization_mode=normalization_mode,
        n_eval_dates=len(eval_dates),
        n_eval_points=len(eval_points),
        overall_ic=overall_ic,
        overall_p_value=overall_p,
        per_segment_ic=per_segment_results,
        baskets=basket_snapshots,
        fixed_vs_rolling=None,
        seed_share_warning_dates=seed_share_warning_dates,
    )
    return report, eval_points


def _build_fixed_vs_rolling(
    fixed_points: list[EvalPoint],
    rolling_points: list[EvalPoint],
    fixed_report: BacktestReport,
    rolling_report: BacktestReport,
) -> dict[str, Any]:
    """Compare fixed-band and rolling-band backtest outputs."""
    fixed_by_key: dict[tuple[str, date, str], EvalPoint] = {(p.segment, p.eval_date, p.ticker): p for p in fixed_points}
    rolling_by_key: dict[tuple[str, date, str], EvalPoint] = {
        (p.segment, p.eval_date, p.ticker): p for p in rolling_points
    }
    common_keys = sorted(set(fixed_by_key) & set(rolling_by_key))

    per_segment: dict[str, dict[str, Any]] = {}
    for key in common_keys:
        seg = key[0]
        f = fixed_by_key[key]
        r = rolling_by_key[key]
        entry = per_segment.setdefault(
            seg,
            {"segment": seg, "abs_diffs": [], "regime_flips": 0},
        )
        entry["abs_diffs"].append(abs(f.b - r.b))
        if f.regime != r.regime:
            entry["regime_flips"] += 1

    per_segment_rows = []
    for seg in sorted(per_segment):
        entry = per_segment[seg]
        diffs = entry["abs_diffs"]
        per_segment_rows.append(
            {
                "segment": seg,
                "mean_abs_b_diff": sum(diffs) / len(diffs) if diffs else None,
                "regime_flips": entry["regime_flips"],
                "n_common_points": len(diffs),
            }
        )

    return {
        "fixed_overall_ic": fixed_report.overall_ic,
        "rolling_overall_ic": rolling_report.overall_ic,
        "fixed_n_eval_points": fixed_report.n_eval_points,
        "rolling_n_eval_points": rolling_report.n_eval_points,
        "per_segment": per_segment_rows,
    }


def run_backtest(
    *,
    prices: PriceProvider,
    factory: sessionmaker,
    universe_path: Path = _DEFAULT_UNIVERSE,
    start: date,
    end: date,
    forward_days: int = 90,
    horizon: str = "near",
    normalization_mode: str = "fixed",
) -> BacktestReport:
    """Compute the walk-forward correlations.

    Runs both fixed and rolling normalization modes and returns the
    report for the requested primary mode, with a `fixed_vs_rolling`
    comparison attached.

    The function is pure compute over the inputs. No side effects.
    """
    fixed_report, fixed_points = _run_single_mode(
        prices=prices,
        factory=factory,
        universe_path=universe_path,
        start=start,
        end=end,
        forward_days=forward_days,
        horizon=horizon,
        normalization_mode="fixed",
    )
    rolling_report, rolling_points = _run_single_mode(
        prices=prices,
        factory=factory,
        universe_path=universe_path,
        start=start,
        end=end,
        forward_days=forward_days,
        horizon=horizon,
        normalization_mode="rolling",
    )

    fixed_vs_rolling = _build_fixed_vs_rolling(fixed_points, rolling_points, fixed_report, rolling_report)

    if normalization_mode == "rolling":
        primary_report = rolling_report
    else:
        primary_report = fixed_report
    return replace(primary_report, fixed_vs_rolling=fixed_vs_rolling)


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
    parser.add_argument(
        "--normalization-mode",
        choices=("fixed", "rolling", "both"),
        default="fixed",
        help="Primary score normalization mode to report; fixed and rolling are always computed. Default: fixed.",
    )
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
        normalization_mode=args.normalization_mode,
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
