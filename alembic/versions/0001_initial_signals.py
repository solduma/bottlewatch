"""initial signals + ingest_runs tables

Revision ID: 0001_initial_signals
Revises:
Create Date: 2026-06-03

Hand-authored (no autogenerate in M1 — the schema is small and we
want the diff to be reviewable). Mirrors `bottlewatch.app.db.models`.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0001_initial_signals"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "signals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("segment", sa.String(), nullable=False),
        sa.Column("subsegment", sa.String(), nullable=True),
        sa.Column("signal_name", sa.String(), nullable=False),
        sa.Column("value_num", sa.Float(), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("unit", sa.String(), nullable=True),
        sa.Column("geography", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("source_id", sa.String(), nullable=True),
        sa.Column("observed_at", sa.Date(), nullable=False),
        sa.Column("ingested_at", sa.DateTime(), nullable=False),
        sa.Column("tickers", sa.Text(), nullable=True),
    )
    op.create_index("ix_signals_segment_obs", "signals", ["segment", "observed_at"])
    op.create_index("ix_signals_source_sourceid", "signals", ["source", "source_id"])

    op.create_table(
        "ingest_runs",
        sa.Column("source", sa.String(), primary_key=True),
        sa.Column("last_ingested_at", sa.DateTime(), nullable=False),
        sa.Column("rows_written", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("ingest_runs")
    op.drop_index("ix_signals_source_sourceid", table_name="signals")
    op.drop_index("ix_signals_segment_obs", table_name="signals")
    op.drop_table("signals")
