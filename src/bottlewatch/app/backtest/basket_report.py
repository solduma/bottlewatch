"""Serializable report dataclasses for the backtest job."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True)
class BasketSnapshot:
    """One basket at one evaluation date."""

    eval_date: date
    side: str
    segments: list[str]
    tickers: list[str]
    equal_weight_return: float | None
    coverage: float


@dataclass(frozen=True)
class SegmentICRow:
    """IC result for one segment."""

    segment: str
    n: int
    rho: float
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
