"""GET /api/v1/screener?side=long|short&horizon=near|med|long.

The conviction-basket builder. Per plan §7.4, the long basket is a
**hard guard**: it REFUSES to add any (segment, horizon) pair
where the segment’s regime is RESOLVING, with no override. The
short basket returns RESOLVING segments ranked by B × |B'|.

Both endpoints are segment-level (one row per eligible segment).
Ticker-level rows are M3 work.

The screener also excludes NO_DATA segments (no score → not
investable).
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from bottlewatch.app.db import Score
from bottlewatch.app.score.regime import Regime


router = APIRouter(tags=["screener"])

VALID_HORIZONS = ("near", "med", "long")
VALID_SIDES = ("long", "short")
EXCLUDED_REGIMES_LONG = (
    Regime.RESOLVING.value,
    Regime.RESOLVING_FROM_LOW.value,
    Regime.NO_DATA.value,
)


class ScreenerRow(BaseModel):
    segment: str
    horizon: str
    score: float | None
    momentum: float | None
    regime: str
    regime_confidence: str
    data_completeness: float
    computed_at: datetime
    # For short: the B × |B'| rank key (debugging-friendly)
    rank_key: float | None = None


def _query_scores(factory: sessionmaker, horizon: str) -> list[Score]:
    with factory() as session:
        return list(
            session.execute(select(Score).where(Score.horizon == horizon).order_by(Score.segment.asc())).scalars().all()
        )


@router.get("/screener", response_model=list[ScreenerRow])
def get_screener(
    request: Request,
    side: str = Query(description="long | short"),
    horizon: str = Query(description="near | med | long"),
) -> list[ScreenerRow]:
    if side not in VALID_SIDES:
        raise HTTPException(
            status_code=400,
            detail=f"unknown side: {side!r}; expected one of {list(VALID_SIDES)}",
        )
    if horizon not in VALID_HORIZONS:
        raise HTTPException(
            status_code=400,
            detail=f"unknown horizon: {horizon!r}; expected one of {list(VALID_HORIZONS)}",
        )

    factory: sessionmaker = request.app.state.session_factory
    rows = _query_scores(factory, horizon)

    if side == "long":
        # Hard guard: exclude RESOLVING + RESOLVING-FROM-LOW + NO_DATA.
        # The methodology says NO_DATA is "honest no data" — not
        # investable, so it gets dropped here too.
        eligible = [r for r in rows if r.regime not in EXCLUDED_REGIMES_LONG]
        eligible.sort(key=lambda r: (-(r.score or 0.0), -(r.momentum or 0.0)))
        return [ScreenerRow(**_score_to_screener_row(r)) for r in eligible]

    # side == "short"
    resolving = [r for r in rows if r.regime == "RESOLVING" and r.score is not None and r.momentum is not None]
    # Sort by B × |B'| descending. The list filter guarantees both
    # fields are non-None, but the lambda needs explicit guards for
    # the type checker.
    resolving.sort(key=lambda r: -((r.score or 0.0) * abs(r.momentum or 0.0)))
    return [ScreenerRow(**_score_to_screener_row(r, include_rank=True)) for r in resolving]


def _score_to_screener_row(s: Score, *, include_rank: bool = False) -> dict:
    out = {
        "segment": s.segment,
        "horizon": s.horizon,
        "score": s.score,
        "momentum": s.momentum,
        "regime": s.regime,
        "regime_confidence": s.regime_confidence,
        "data_completeness": s.data_completeness,
        "computed_at": s.computed_at,
        "rank_key": (s.score * abs(s.momentum))
        if (include_rank and s.score is not None and s.momentum is not None)
        else None,
    }
    return out
