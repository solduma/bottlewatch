"""GET /api/v1/signals?segment=...&limit=50."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from bottlewatch.app.api.segments import SignalRow


router = APIRouter(tags=["signals"])


@router.get("/signals", response_model=list[SignalRow])
def list_signals(
    request: Request,
    segment: str | None = Query(default=None, description="Filter by segment slug."),
    limit: int = Query(default=50, ge=1, le=500, description="Max rows to return."),
) -> list[SignalRow]:
    from bottlewatch.app.api.services import list_signals as svc

    rows = svc(request.app.state.session_factory, segment=segment, limit=limit)
    return [SignalRow(**r) for r in rows]
