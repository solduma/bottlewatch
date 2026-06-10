"""GET /api/v1/segments, /api/v1/segments/{slug}."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel


router = APIRouter(tags=["segments"])

VALID_HORIZONS = ("near", "med", "long")


class SegmentScore(BaseModel):
    segment: str
    horizon: str
    score: float | None
    momentum: float | None
    regime: str
    regime_confidence: str
    data_completeness: float
    computed_at: datetime


class SignalRow(BaseModel):
    id: int
    segment: str
    subsegment: str | None
    signal_name: str
    value_num: float | None
    value_text: str | None
    unit: str | None
    geography: str | None
    source: str
    source_id: str | None
    observed_at: datetime


class SegmentDetail(BaseModel):
    segment: str
    horizons: list[SegmentScore]
    sub_scores: dict[str, float | None]
    signals: list[SignalRow]


@router.get("/segments", response_model=list[SegmentScore])
def list_segments(
    request: Request,
    horizon: str | None = Query(
        default=None,
        description="Filter to one horizon (near | med | long). Omit for all 3.",
    ),
) -> list[SegmentScore]:
    from bottlewatch.app.api.services import list_segment_scores

    if horizon is not None and horizon not in VALID_HORIZONS:
        raise HTTPException(
            status_code=400,
            detail=f"unknown horizon: {horizon!r}; expected one of {list(VALID_HORIZONS)}",
        )
    rows = list_segment_scores(request.app.state.session_factory, horizon=horizon)
    return [SegmentScore(**r) for r in rows]


@router.get("/segments/{slug}", response_model=SegmentDetail)
def get_segment(slug: str, request: Request) -> SegmentDetail:
    from bottlewatch.app.api.services import get_segment_detail

    detail = get_segment_detail(request.app.state.session_factory, slug)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"unknown segment: {slug}")
    return SegmentDetail(
        segment=detail["segment"],
        horizons=[SegmentScore(**h) for h in detail["horizons"]],
        sub_scores=detail["sub_scores"],
        signals=[SignalRow(**s) for s in detail["signals"]],
    )
