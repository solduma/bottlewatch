"""Tests for score_history wiring in the recompute job.

Verifies:
- Running recompute writes 30 score_history rows
- Running twice produces accumulated rows (append, not replace)
- The prune deletes rows older than 12 months
"""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from bottlewatch.app.db import ScoreHistory, init_schema, make_engine, make_session_factory, session_scope
from bottlewatch.config import Settings
from bottlewatch.jobs import recompute_scores


def test_score_history_job_writes_30_rows(tmp_path: Path) -> None:
    """A clean factory gets 30 score_history rows from one recompute run."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        engine = make_engine(f"sqlite:///{path}")
        init_schema(engine)
        factory = make_session_factory(engine)
        settings = Settings(
            app_env="test",
            database_url=f"sqlite:///{path}",
            refresh_log_path=tmp_path / "refresh.log",
        )
        recompute_scores.run(factory=factory, settings=settings)
        with session_scope(factory) as session:
            count = session.execute(select(ScoreHistory.id)).scalars().all()
        assert len(count) == 30  # 10 segments × 3 horizons
        assert len(set(count)) == 30  # all unique auto-increment
        engine.dispose()
    finally:
        os.unlink(path)


def test_score_history_accumulates_across_runs(tmp_path: Path) -> None:
    """Two recompute runs produce 60 rows (append, not replace)."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        engine = make_engine(f"sqlite:///{path}")
        init_schema(engine)
        factory = make_session_factory(engine)
        settings = Settings(
            app_env="test",
            database_url=f"sqlite:///{path}",
            refresh_log_path=tmp_path / "refresh.log",
        )
        recompute_scores.run(factory=factory, settings=settings)
        recompute_scores.run(factory=factory, settings=settings)
        with session_scope(factory) as session:
            count = session.execute(select(ScoreHistory.id)).scalars().all()
        assert len(count) == 60
        engine.dispose()
    finally:
        os.unlink(path)


def test_score_history_prunes_older_than_12_months(tmp_path: Path) -> None:
    """A stale row (older than the 1000-day retention) is removed on the next recompute.

    The m4 work bumped score_history retention to 1000 days to
    support multi-year backtests (see `m4-backtest-initial.md`).
    The 12-month figure in the test name is the original M3
    retention; the test body asserts against the *current*
    retention to stay in sync with `recompute_scores._RETENTION_DAYS`.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        engine = make_engine(f"sqlite:///{path}")
        init_schema(engine)
        factory = make_session_factory(engine)
        settings = Settings(
            app_env="test",
            database_url=f"sqlite:///{path}",
            refresh_log_path=tmp_path / "refresh.log",
        )
        now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        # Insert a stale row (1100 days old — well past the 1000-day retention).
        with session_scope(factory) as session:
            session.add(
                ScoreHistory(
                    segment="advanced_packaging",
                    horizon="near",
                    b=80.0,
                    momentum=-10.0,
                    regime="RESOLVING",
                    computed_at=now - timedelta(days=1100),
                )
            )
        # Confirm stale row exists.
        with session_scope(factory) as session:
            count = session.execute(select(ScoreHistory.id)).scalars().all()
        assert len(count) == 1
        # Run recompute — stale row should be pruned, 30 fresh rows added.
        recompute_scores.run(factory=factory, settings=settings)
        with session_scope(factory) as session:
            all_rows = session.execute(
                select(ScoreHistory.segment, ScoreHistory.horizon, ScoreHistory.computed_at).where(
                    ScoreHistory.segment == "advanced_packaging", ScoreHistory.horizon == "near"
                )
            ).all()
        assert len(all_rows) == 1  # one fresh row
        # Confirm it's the fresh one (within 1 minute of now).
        seg, hor, comp_at = all_rows[0]
        assert (now - comp_at.replace(tzinfo=None)).total_seconds() < 60
        engine.dispose()
    finally:
        os.unlink(path)
