"""Service layer for the API.

Owns the DB session and the SQLAlchemy queries. Routers import
these functions; the functions do not import FastAPI. Keeping
the I/O in one place makes the routers trivially testable
(via `httpx.AsyncClient` against `app.main.create_app`).

Why sync SQLAlchemy here even though the routers are async? Per
the M2 plan: SQLite + sync is fast enough for a personal
dashboard, and dual engines would add `app.dependency_overrides`
plumbing for no measurable win. We revisit async at the v1.1
Postgres cutover.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from bottlewatch.app.db import Score, Signal

_LOGGER = logging.getLogger(__name__)


def health_snapshot(factory: sessionmaker) -> dict[str, Any]:
    """Return DB liveness + last score recompute + signal count.

    The dashboard footer reads this to display "is the data
    stale?". `db_ok` is True if we got any answer at all; we
    do not recheck the connection (the engine is already
    pool-managed).
    """
    try:
        with factory() as session:
            last_score_at = session.execute(select(func.max(Score.computed_at))).scalar()
            signals_count = session.execute(select(func.count(Signal.id))).scalar() or 0
        return {
            "db_ok": True,
            "last_score_at": last_score_at,
            "signals_count": int(signals_count),
        }
    except Exception as e:  # noqa: BLE001 — health endpoint should not raise
        _LOGGER.exception("health snapshot failed: %s", e)
        return {
            "db_ok": False,
            "last_score_at": None,
            "signals_count": 0,
        }


def list_segment_scores(
    factory: sessionmaker,
    horizon: str | None = None,
) -> list[dict[str, Any]]:
    """Return one row per (segment, horizon) from the `scores` table.

    When `horizon` is provided, returns only the 10 rows for that
    horizon. When None, returns all 30 rows.
    """
    with factory() as session:
        stmt = select(Score).order_by(Score.segment.asc(), Score.horizon.asc())
        if horizon is not None:
            stmt = stmt.where(Score.horizon == horizon)
        rows = session.execute(stmt).scalars().all()
        return [_score_to_dict(r) for r in rows]


def get_segment_detail(factory: sessionmaker, slug: str) -> dict[str, Any] | None:
    """Return all 3 horizons of one segment + its recent signals.

    Returns None if the segment has no scores row (the router
    turns that into 404).
    """
    with factory() as session:
        score_rows = (
            session.execute(select(Score).where(Score.segment == slug).order_by(Score.horizon.asc())).scalars().all()
        )
        if not score_rows:
            return None
        signal_rows = (
            session.execute(select(Signal).where(Signal.segment == slug).order_by(Signal.observed_at.desc()).limit(50))
            .scalars()
            .all()
        )
    return {
        "segment": slug,
        "horizons": [_score_to_dict(r) for r in score_rows],
        "sub_scores": score_rows[0].sub_scores,  # all 3 horizons share the same sub-scores
        "signals": [_signal_to_dict(s) for s in signal_rows],
    }


def list_signals(
    factory: sessionmaker,
    segment: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return recent signals, optionally filtered by segment."""
    stmt = select(Signal).order_by(Signal.observed_at.desc()).limit(limit)
    if segment is not None:
        stmt = stmt.where(Signal.segment == segment)
    with factory() as session:
        rows = session.execute(stmt).scalars().all()
        return [_signal_to_dict(s) for s in rows]


# ---------------------------------------------------------------------------
# Row → dict helpers
# ---------------------------------------------------------------------------


def _score_to_dict(s: Score) -> dict[str, Any]:
    return {
        "segment": s.segment,
        "horizon": s.horizon,
        "score": s.score,
        "momentum": s.momentum,
        "regime": s.regime,
        "regime_confidence": s.regime_confidence,
        "data_completeness": s.data_completeness,
        "computed_at": s.computed_at,
    }


def _signal_to_dict(s: Signal) -> dict[str, Any]:
    return {
        "id": s.id,
        "segment": s.segment,
        "subsegment": s.subsegment,
        "signal_name": s.signal_name,
        "value_num": s.value_num,
        "value_text": s.value_text,
        "unit": s.unit,
        "geography": s.geography,
        "source": s.source,
        "source_id": s.source_id,
        "observed_at": s.observed_at,
    }
