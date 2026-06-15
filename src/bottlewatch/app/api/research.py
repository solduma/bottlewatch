"""GET /api/v1/research/daily.

Returns the daily research rationale + divergence audit for one
(segment, horizon, date) tuple. Defaults to today's snapshot.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from bottlewatch.app.db import ResearchSnapshot


router = APIRouter(tags=["research"])

VALID_HORIZONS = ("near", "med", "long", "all")


class DivergenceItem(BaseModel):
    sub_score: str
    seed: float
    dynamic: float
    gap: float


class ResearchSnapshotRow(BaseModel):
    segment: str
    horizon: str
    date: date
    rationale_md: str
    divergences: list[DivergenceItem]
    generated_by: str
    created_at: datetime


@router.get("/research/daily", response_model=ResearchSnapshotRow)
def get_research_daily(
    request: Request,
    segment: str = Query(..., description="Segment slug."),
    horizon: str = Query(default="all", description="near | med | long | all"),
    date: date | None = Query(default=None, description="Snapshot date (YYYY-MM-DD). Default: today."),
) -> ResearchSnapshotRow:
    if horizon not in VALID_HORIZONS:
        raise HTTPException(
            status_code=400,
            detail=f"unknown horizon: {horizon!r}; expected one of {list(VALID_HORIZONS)}",
        )

    target_date = date or datetime.now(tz=timezone.utc).date()
    factory: sessionmaker = request.app.state.session_factory

    with factory() as session:
        row = session.execute(
            select(ResearchSnapshot)
            .where(ResearchSnapshot.segment == segment)
            .where(ResearchSnapshot.horizon == horizon)
            .where(ResearchSnapshot.date == target_date)
        ).scalar_one_or_none()

    if row is None:
        # Give a clear 404 with the missing key so the caller knows
        # whether to run `bottlewatch-research` or wait for the next
        # scheduled run.
        raise HTTPException(
            status_code=404,
            detail=f"no research snapshot for {segment}/{horizon} on {target_date.isoformat()}",
        )

    return ResearchSnapshotRow(
        segment=row.segment,
        horizon=row.horizon,
        date=row.date,
        rationale_md=row.rationale_md,
        divergences=[DivergenceItem(**d) for d in row.divergences],
        generated_by=row.generated_by,
        created_at=row.created_at,
    )
