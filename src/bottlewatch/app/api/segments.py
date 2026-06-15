"""GET /api/v1/segments, /api/v1/segments/{slug}."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from bottlewatch.app import segments_meta


router = APIRouter(tags=["segments"])
VALID_HORIZONS = ("near", "med", "long")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SEGMENT_BRIEFS_PATH = _PROJECT_ROOT / "app" / "segment_briefs.json"


def _load_segment_briefs() -> dict[str, dict]:
    """Load the hand-authored segment briefs exported from research/01_segments.

    The JSON is a one-time extraction of the definition, momentum, resolution,
    and regime-call sections of each segment markdown file. Missing slugs
    degrade gracefully to an empty dict.
    """
    try:
        with open(_SEGMENT_BRIEFS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


_SEGMENT_BRIEFS = _load_segment_briefs()


class SubScoreValue(BaseModel):
    value: float | None
    raw_value: float | None
    source: str
    confidence: str
    imputed: bool
    normalization_mode: str | None = None


class SegmentScore(BaseModel):
    segment: str
    name: str
    horizon: str
    score: float | None
    momentum: float | None
    regime: str
    regime_confidence: str
    data_completeness: float
    static_seed_share: float
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


class SegmentBrief(BaseModel):
    title: str
    summary: str
    momentum_summary: str
    resolution_summary: str
    regime_call_md: str


class SegmentDetail(BaseModel):
    segment: str
    name: str
    horizons: list[SegmentScore]
    sub_scores: dict[str, SubScoreValue]
    signals: list[SignalRow]
    brief: SegmentBrief | None = None


def _row_with_name(d: dict) -> dict:
    """Return a copy of `d` with a `name` field and `sector` field added.

    Helper for the two endpoints below so the slug → name and
    slug → sector lookups happen in one place.
    """
    return {
        **d,
        "name": segments_meta.display_name(d["segment"]),
        "sector": segments_meta.sector_for_segment(d["segment"]),
    }


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
    return [SegmentScore(**_row_with_name(r)) for r in rows]


@router.get("/segments/{slug}", response_model=SegmentDetail)
def get_segment(slug: str, request: Request) -> SegmentDetail:
    from bottlewatch.app.api.services import get_segment_detail

    detail = get_segment_detail(request.app.state.session_factory, slug)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"unknown segment: {slug}")
    brief_data = _SEGMENT_BRIEFS.get(slug)
    brief = SegmentBrief(**brief_data) if brief_data else None
    return SegmentDetail(
        segment=detail["segment"],
        name=segments_meta.display_name(detail["segment"]),
        horizons=[SegmentScore(**_row_with_name(h)) for h in detail["horizons"]],
        sub_scores=detail["sub_scores"],
        signals=[SignalRow(**s) for s in detail["signals"]],
        brief=brief,
    )
