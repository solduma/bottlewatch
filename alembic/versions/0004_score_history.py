"""score_history table (M3)

Revision ID: 0004_score_history
Revises: 0003_thesis
Create Date: 2026-06-04

Append-only log of computed B values per (segment, horizon). One row
per recompute run. The recompute job appends; the momentum formula
reads the trailing 6 months to compute B'. Retention: 12 months;
the recompute job prunes older rows on each run.

The v1.1 score history table that fixes the momentum = 0 bug from M2.
Before this table exists, b_history is always None and momentum = 0.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0004_score_history"
down_revision = "0003_thesis"
branch_labels = None
depends_on = None


_HORIZON_CHECK = "horizon IN ('near', 'med', 'long')"


def upgrade() -> None:
    op.create_table(
        "score_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("segment", sa.String(), nullable=False),
        sa.Column("horizon", sa.String(), nullable=False),
        sa.Column("b", sa.Float(), nullable=True),
        sa.Column("momentum", sa.Float(), nullable=True),
        sa.Column("regime", sa.String(), nullable=False),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(_HORIZON_CHECK, name="ck_score_history_horizon"),
    )
    op.create_index(
        "ix_score_history_seg_hor_comp",
        "score_history",
        ["segment", "horizon", "computed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_score_history_seg_hor_comp", table_name="score_history")
    op.drop_table("score_history")
