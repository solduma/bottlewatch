"""GET /api/v1/scores/regime and GET /api/v1/scores/history.

- /scores/regime: the 2x2 quadrant payload (M2).
- /scores/history: per-segment B and B' over time (M3). Supports
  two modes:
  - `?segment=X&horizon=Y` (single segment, used by /tickers/[ticker])
  - `?segments=a,b,c&horizon=Y` (batched, used by the scoreboard
    to fetch all sparkline series in one round-trip)
  The two are mutually exclusive; both → 400.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query, Request

from bottlewatch.app.api.segments import SegmentScore


router = APIRouter(tags=["scores"])


@router.get("/scores/regime", response_model=list[SegmentScore])
def get_regime(
    request: Request,
    horizon: str | None = Query(
        default=None,
        description="Filter to one horizon (near | med | long). Omit for all 3.",
    ),
) -> list[SegmentScore]:
    from bottlewatch.app.api.services import list_segment_scores
    from bottlewatch.app.api.segments import _row_with_name

    rows = list_segment_scores(request.app.state.session_factory, horizon=horizon)
    return [SegmentScore(**_row_with_name(r)) for r in rows]


def _history_rows_for(factory, segment: str, horizon: str, cutoff: datetime) -> list[dict]:
    """Read ScoreHistory rows for one (segment, horizon) into a JSON-ready list.

    Shared by the single-`segment` and batched-`segments` paths so the
    row shape stays identical across both.
    """
    from bottlewatch.app.db import ScoreHistory
    from sqlalchemy import select

    with factory() as session:
        rows = (
            session.execute(
                select(ScoreHistory)
                .where(
                    ScoreHistory.segment == segment,
                    ScoreHistory.horizon == horizon,
                    ScoreHistory.computed_at >= cutoff,
                )
                .order_by(ScoreHistory.computed_at.asc())
            )
            .scalars()
            .all()
        )
    return [
        {
            "computed_at": r.computed_at,
            "b": r.b,
            "momentum": r.momentum,
            "regime": r.regime,
        }
        for r in rows
    ]


@router.get("/scores/history", response_model=dict)
def get_scores_history(
    request: Request,
    segment: str | None = Query(
        default=None,
        description="One segment slug. Mutually exclusive with `segments`.",
    ),
    segments: str | None = Query(
        default=None,
        description="Comma-separated segment slugs. Mutually exclusive with `segment`.",
    ),
    horizon: str = Query(..., description="Horizon: near | med | long."),
    months: int = Query(default=6, ge=1, le=36, description="Months of history to return."),
) -> dict:
    if horizon not in ("near", "med", "long"):
        raise HTTPException(status_code=400, detail=f"unknown horizon: {horizon!r}")
    if segment is not None and segments is not None:
        raise HTTPException(
            status_code=400,
            detail="`segment` and `segments` are mutually exclusive; pass only one",
        )

    factory = request.app.state.session_factory
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=months * 30)

    if segments is not None:
        # Batched: one entry per requested segment, in request order.
        # Empty string or whitespace-only is a programmer error.
        slugs = [s.strip() for s in segments.split(",") if s.strip()]
        if not slugs:
            raise HTTPException(status_code=400, detail="`segments` must list at least one segment")
        return {
            "horizon": horizon,
            "months": months,
            "series": [
                {"segment": slug, "points": _history_rows_for(factory, slug, horizon, cutoff)} for slug in slugs
            ],
        }

    # Single-segment path: backward-compat for /tickers/[ticker] and
    # any external consumer. `segment` is required here; if it's
    # None, FastAPI raised 422 above (it's typed `str | None` for
    # the mutually-exclusive check but `None` falls through to
    # a 400 — clearer message than 422's "field required").
    if segment is None:
        raise HTTPException(
            status_code=400,
            detail="`segment` (single) or `segments` (batched) is required",
        )
    return {
        "segment": segment,
        "horizon": horizon,
        "points": _history_rows_for(factory, segment, horizon, cutoff),
    }
