"""scores table (M2)

Revision ID: 0002_scores
Revises: 0001_initial_signals
Create Date: 2026-06-04

Hand-authored (matching 0001's style). One row per (segment, horizon)
- up to 11 segments × 3 horizons = 33 rows. The recompute job
rebuilds the table atomically (delete + insert in a transaction),
so the API never sees a half-populated state.

`sub_scores` is JSON for forward-compat with Postgres (the v1.1
cutover target). SQLite stores JSON as TEXT under the hood; the
dialect handles the round-trip.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_scores"
down_revision = "0001_initial_signals"
branch_labels = None
depends_on = None

_HORIZON_CHECK = "horizon IN ('near', 'med', 'long')"


def upgrade() -> None:
    op.create_table(
        "scores",
        sa.Column("segment", sa.String(), nullable=False),
        sa.Column("horizon", sa.String(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("momentum", sa.Float(), nullable=True),
        sa.Column("regime", sa.String(), nullable=False),
        sa.Column("regime_confidence", sa.String(), nullable=False),
        sa.Column("sub_scores", sa.JSON(), nullable=False),
        sa.Column("data_completeness", sa.Float(), nullable=False),
        sa.Column("first_computed_at", sa.DateTime(), nullable=False),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("segment", "horizon", name="pk_scores"),
        sa.CheckConstraint(_HORIZON_CHECK, name="ck_scores_horizon"),
    )
    op.create_index("ix_scores_computed_at", "scores", ["computed_at"])


def downgrade() -> None:
    op.drop_index("ix_scores_computed_at", table_name="scores")
    op.drop_table("scores")
