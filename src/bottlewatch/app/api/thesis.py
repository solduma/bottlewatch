"""GET/POST/PUT/DELETE /api/v1/thesis.

User-authored thesis notes — the override-audit-trail for the hard
guard. A user who wants to argue against a RESOLVING regime writes
a thesis note here; the basket builder then surfaces the note in
the UI when the guard fires.

`body_md` is stored as markdown text. The frontend (TipTap) handles
serialization/deserialization via its markdown extension. Keeping
plain markdown in the DB keeps it readable via `psql` and the
round-trip simple.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field


router = APIRouter(tags=["thesis"])


class ThesisCreate(BaseModel):
    segment: str = Field(..., min_length=1)
    ticker: str | None = None
    side: str | None = None
    body_md: str = Field(..., min_length=1)


class ThesisRow(BaseModel):
    id: int
    segment: str
    ticker: str | None
    side: str | None
    body_md: str
    created_at: datetime
    updated_at: datetime


@router.get("/thesis", response_model=list[ThesisRow])
def list_thesis(
    request: Request,
    segment: str | None = Query(default=None, description="Filter by segment slug."),
    ticker: str | None = Query(default=None, description="Filter by ticker."),
    side: str | None = Query(default=None, description="Filter by side (long | short)."),
) -> list[ThesisRow]:
    from bottlewatch.app.db import Thesis
    from sqlalchemy import select

    factory = request.app.state.session_factory
    with factory() as session:
        stmt = select(Thesis).order_by(Thesis.updated_at.desc())
        if segment is not None:
            stmt = stmt.where(Thesis.segment == segment)
        if ticker is not None:
            stmt = stmt.where(Thesis.ticker == ticker)
        if side is not None:
            stmt = stmt.where(Thesis.side == side)
        rows = session.execute(stmt).scalars().all()
    return [
        ThesisRow(
            id=r.id,
            segment=r.segment,
            ticker=r.ticker,
            side=r.side,
            body_md=r.body_md,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


@router.post("/thesis", response_model=ThesisRow, status_code=201)
def create_thesis(request: Request, body: ThesisCreate) -> ThesisRow:
    from bottlewatch.app.db import Thesis

    factory = request.app.state.session_factory
    now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    thesis = Thesis(
        segment=body.segment,
        ticker=body.ticker,
        side=body.side,
        body_md=body.body_md,
        created_at=now,
        updated_at=now,
    )
    with factory() as session:
        session.add(thesis)
        session.commit()
        session.refresh(thesis)
    return ThesisRow(
        id=thesis.id,
        segment=thesis.segment,
        ticker=thesis.ticker,
        side=thesis.side,
        body_md=thesis.body_md,
        created_at=thesis.created_at,
        updated_at=thesis.updated_at,
    )


@router.put("/thesis/{thesis_id}", response_model=ThesisRow)
def update_thesis(
    request: Request,
    body: ThesisCreate,
    thesis_id: int = Path(...),
) -> ThesisRow:
    """Replace an existing thesis note. Full replacement of the editable fields."""
    from bottlewatch.app.db import Thesis

    factory = request.app.state.session_factory
    with factory() as session:
        thesis = session.get(Thesis, thesis_id)
        if thesis is None:
            raise HTTPException(status_code=404, detail=f"thesis {thesis_id} not found")
        thesis.segment = body.segment
        thesis.ticker = body.ticker
        thesis.side = body.side
        thesis.body_md = body.body_md
        thesis.updated_at = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        session.commit()
        session.refresh(thesis)
    return ThesisRow(
        id=thesis.id,
        segment=thesis.segment,
        ticker=thesis.ticker,
        side=thesis.side,
        body_md=thesis.body_md,
        created_at=thesis.created_at,
        updated_at=thesis.updated_at,
    )


@router.delete("/thesis/{thesis_id}", status_code=204)
def delete_thesis(request: Request, thesis_id: int = Path(...)) -> None:
    from bottlewatch.app.db import Thesis

    factory = request.app.state.session_factory
    with factory() as session:
        thesis = session.get(Thesis, thesis_id)
        if thesis is None:
            raise HTTPException(status_code=404, detail=f"thesis {thesis_id} not found")
        session.delete(thesis)
        session.commit()
