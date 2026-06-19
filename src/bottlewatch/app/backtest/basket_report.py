"""Serializable report dataclasses for the backtest job."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True)
class BasketSnapshot:
    """One basket at one evaluation date."""

    eval_date: date
    side: str
    segments: list[str]
    tickers: list[str]
    weights: dict[str, float] = field(default_factory=dict)
    equal_weight_return: float | None = None
    net_return: float | None = None
    volatility: float | None = None
    max_drawdown: float | None = None
    hit_rate: float | None = None
    coverage: float = 0.0
    sector_neutral: bool = False


@dataclass(frozen=True)
class SegmentICRow:
    """IC result for one segment.

    `rho` is None when the segment's score did not vary over the
    backtest window (e.g., historical recomputes used static seeds with
    no time-varying inputs), making Spearman correlation undefined.
    """

    segment: str
    n: int
    rho: float | None
    p_value: float | None
    ci_low: float | None
    ci_high: float | None
    bh_rejected: bool


@dataclass(frozen=True)
class BacktestReport:
    """Full backtest report."""

    horizon: str
    forward_days: int
    start: date
    end: date
    normalization_mode: str
    n_eval_dates: int
    n_eval_points: int
    overall_ic: float | None
    overall_p_value: float | None
    per_segment_ic: list[SegmentICRow]
    baskets: list[BasketSnapshot]
    fixed_vs_rolling: dict[str, Any] | None
    seed_share_warning_dates: list[date]
    overall_ci_low: float | None = None
    overall_ci_high: float | None = None
    n_constant_score_segments: int = 0
    n_segments_evaluated: int = 0
    # Point-in-time disclosure: basket ticker membership is gated as-of by price
    # existence, but mcap_usd/exposure_pct are static present-day values (no
    # historical fundamentals source), so baskets are not fully point-in-time.
    universe_is_point_in_time: bool = False
    universe_caveat: str = ""

    def to_jsonable(self) -> dict[str, Any]:
        def _convert(value: Any) -> Any:
            if isinstance(value, date):
                return value.isoformat()
            if isinstance(value, list):
                return [_convert(v) for v in value]
            if isinstance(value, dict):
                return {k: _convert(v) for k, v in value.items()}
            if hasattr(value, "__dataclass_fields__"):
                return _convert(asdict(value))
            return value

        return _convert(asdict(self))
