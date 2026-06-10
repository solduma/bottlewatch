"""GET /api/v1/health."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel
from datetime import datetime


router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    db_ok: bool
    last_score_at: datetime | None
    signals_count: int


@router.get("/health", response_model=HealthResponse)
def get_health(request: Request) -> HealthResponse:
    from bottlewatch.app.api.services import health_snapshot

    snapshot = health_snapshot(request.app.state.session_factory)
    return HealthResponse(**snapshot)
