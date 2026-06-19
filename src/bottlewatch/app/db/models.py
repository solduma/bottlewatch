"""SQLAlchemy ORM models for the bottlewatch pipeline.

Five tables (M3):

- `signals` — the v1 canonical schema (plan §3). One row per
  (source, source_id, observed_at). Idempotent inserts rely on
  the orchestrator's bulk-insert path + the source/source_id
  index, not on a DB-level unique constraint, because EIA
  revises historical values within ~7 days.
- `ingest_runs` — the watermark ledger. One row per source. The
  orchestrator upserts on (source) and reads it to decide whether
  the source is fresh.
- `scores` — the materialized bottleneck score. One row per
  (segment, horizon), written by the M2 recompute job. The API
  reads from this table; the recompute job writes it in a single
  transaction. `sub_scores` is JSON (portable to Postgres at v1.1).
- `score_history` — append-only log of computed B values per
  (segment, horizon). One row per recompute run; read by the
  momentum formula to compute B' (6-month % change). Retained
  12 months; pruned by the recompute job each run.
- `thesis` — user-authored notes, one row per (segment, ticker,
  side). The override-audit-trail for the hard guard. Markdown
  body stored as TEXT; TipTap serializes/deserializes on the
  frontend.

All tables are owned by Alembic (`alembic/versions/*.py` is the
source of truth for DDL). M1 also runs `Base.metadata.create_all`
as a developer-ergonomics fallback so a fresh checkout works
without a migration step; this is logged loudly.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Single declarative base for the package."""


class Signal(Base):
    """A single (source, series, time) observation.

    The `tickers` column is JSON-encoded for forward-compat with the
    M3 universe-to-signal mapping; v1 never reads it.
    """

    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    segment: Mapped[str] = mapped_column(String, nullable=False)
    subsegment: Mapped[str | None] = mapped_column(String, nullable=True)
    signal_name: Mapped[str] = mapped_column(String, nullable=False)
    value_num: Mapped[float | None] = mapped_column(Float, nullable=True)
    value_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(String, nullable=True)
    geography: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    source_id: Mapped[str | None] = mapped_column(String, nullable=True)
    observed_at: Mapped[date] = mapped_column(Date, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    tickers: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_signals_segment_obs", "segment", "observed_at"),
        Index("ix_signals_source_sourceid", "source", "source_id"),
    )

    def to_row(self) -> dict[str, Any]:
        """Column-name dict for bulk insert. Keeps the mapping in one place."""
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class IngestRun(Base):
    """Watermark + status ledger for one source's most recent run."""

    __tablename__ = "ingest_runs"

    source: Mapped[str] = mapped_column(String, primary_key=True)
    last_ingested_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    rows_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    def to_row(self) -> dict[str, Any]:
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class Score(Base):
    """Materialized bottleneck score for one (segment, horizon).

    Written by `bottlewatch.jobs.recompute_scores` in a single
    transaction; read by the FastAPI scoreboard endpoints.

    `regime` is one of: PEAKING / PEAKED / RESOLVING / EMERGING /
    STABLE / RESOLVING-from-low / NO_DATA. NO_DATA is a synthetic
    label for segments with `data_completeness < 0.4`; the row is
    still written so the scoreboard can render an honest badge.

    `regime_confidence` reflects the maturity of the momentum
    history: `low` for <90 days, `medium` for 90-180, `high` beyond.
    First compute has zero history (B' = 0), so confidence is `low`
    until ~6mo of nightly recomputes accumulate.
    """

    __tablename__ = "scores"

    segment: Mapped[str] = mapped_column(String, nullable=False)
    horizon: Mapped[str] = mapped_column(String, nullable=False)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    momentum: Mapped[float | None] = mapped_column(Float, nullable=True)
    regime: Mapped[str] = mapped_column(String, nullable=False)
    regime_confidence: Mapped[str] = mapped_column(String, nullable=False)
    sub_scores: Mapped[dict[str, float | None]] = mapped_column(JSON, nullable=False)
    raw_sub_scores: Mapped[dict[str, float | None] | None] = mapped_column(JSON, nullable=True)
    sub_score_provenance: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    static_seed_share: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    data_completeness: Mapped[float] = mapped_column(Float, nullable=False)
    normalization_mode: Mapped[str | None] = mapped_column(String, nullable=True)
    first_computed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("segment", "horizon", name="pk_scores"),
        CheckConstraint("horizon IN ('near', 'med', 'long')", name="ck_scores_horizon"),
        Index("ix_scores_computed_at", "computed_at"),
    )

    def to_row(self) -> dict[str, Any]:
        return {c.name: getattr(self, c.name) for c in self.__table__.columns}


class ScoreHistory(Base):
    """Append-only log of computed B values per (segment, horizon).

    One row per recompute run. The recompute job appends; the API
    reads the trailing N months to compute momentum. Retention:
    12 months; pruned by the recompute job on each run.

    `b` is the score (B) at that point in time. `momentum` is the
    B' computed with the 6-month window available at that time
    (or None on the first run when there was no history yet).
    """

    __tablename__ = "score_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    segment: Mapped[str] = mapped_column(String, nullable=False)
    horizon: Mapped[str] = mapped_column(String, nullable=False)
    b: Mapped[float | None] = mapped_column(Float, nullable=True)
    momentum: Mapped[float | None] = mapped_column(Float, nullable=True)
    regime: Mapped[str] = mapped_column(String, nullable=False)
    normalization_mode: Mapped[str | None] = mapped_column(String, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        Index("ix_score_history_seg_hor_comp", "segment", "horizon", "computed_at"),
        CheckConstraint("horizon IN ('near', 'med', 'long')", name="ck_score_history_horizon"),
    )


class SubScoreHistory(Base):
    """Append-only log of raw and normalized sub-score values.

    One row per (segment, sub_score_name) per recompute run. Used by
    the rolling 5-year normalizer to build point-in-time bands for
    backtests and historical recomputes.
    """

    __tablename__ = "sub_score_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    segment: Mapped[str] = mapped_column(String, nullable=False)
    sub_score_name: Mapped[str] = mapped_column(String, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    raw_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    normalized_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    normalization_mode: Mapped[str | None] = mapped_column(String, nullable=True)
    band_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    band_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    history_span_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (Index("ix_sub_score_history_seg_name_comp", "segment", "sub_score_name", "computed_at"),)


class Thesis(Base):
    """User-authored thesis notes, one row per (segment, ticker, side).

    `side` is "long" | "short" | None. The override-audit-trail for
    the hard guard: a user who wants to argue against a RESOLVING
    regime writes a thesis note here, linked to the (segment, side)
    pair. The basket builder then surfaces the note in the UI.

    `body_md` is the raw markdown text. TipTap serializes/deserializes
    on the frontend to keep the DB readable and the round-trip simple.
    `ticker` is None for segment-level thesis.
    """

    __tablename__ = "thesis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    segment: Mapped[str] = mapped_column(String, nullable=False)
    ticker: Mapped[str | None] = mapped_column(String, nullable=True)
    side: Mapped[str | None] = mapped_column(String, nullable=True)
    body_md: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        Index("ix_thesis_segment", "segment"),
        Index("ix_thesis_ticker", "ticker"),
    )


class ResearchSnapshot(Base):
    """Daily per-segment research rationale + divergence audit.

    Generated by the `bottlewatch-research` job after the nightly
    recompute. Stores both LLM-generated prose and machine-structured
    divergence flags so the frontend can surface "why did this score
    change?" and "is the research seed still credible?".
    """

    __tablename__ = "research_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    segment: Mapped[str] = mapped_column(String, nullable=False)
    horizon: Mapped[str] = mapped_column(String, nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    rationale_md: Mapped[str] = mapped_column(Text, nullable=False)
    divergences: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    generated_by: Mapped[str] = mapped_column(String, nullable=False)  # "llm" | "machine"
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("segment", "horizon", "date", name="uq_research_snapshot_seg_hor_date"),
        Index("ix_research_snapshots_segment_date", "segment", "date"),
        CheckConstraint("horizon IN ('near', 'med', 'long', 'all')", name="ck_research_snapshots_horizon"),
    )
