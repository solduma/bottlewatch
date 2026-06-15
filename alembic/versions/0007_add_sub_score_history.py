"""add sub_score_history and raw_sub_scores columns

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-14

Add a `sub_score_history` table for rolling 5-year normalization and
audit columns (`raw_sub_scores`, `normalization_mode`) to the `scores`
table.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sub_score_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("segment", sa.String(), nullable=False),
        sa.Column("sub_score_name", sa.String(), nullable=False),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
        sa.Column("raw_value", sa.Float(), nullable=True),
        sa.Column("normalized_value", sa.Float(), nullable=True),
        sa.Column("normalization_mode", sa.String(), nullable=True),
        sa.Column("band_min", sa.Float(), nullable=True),
        sa.Column("band_max", sa.Float(), nullable=True),
        sa.Column("history_span_days", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sub_score_history_seg_name_comp",
        "sub_score_history",
        ["segment", "sub_score_name", "computed_at"],
    )
    op.add_column(
        "scores",
        sa.Column("raw_sub_scores", sa.JSON(), nullable=True),
    )
    op.add_column(
        "scores",
        sa.Column("normalization_mode", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scores", "normalization_mode")
    op.drop_column("scores", "raw_sub_scores")
    op.drop_index("ix_sub_score_history_seg_name_comp", table_name="sub_score_history")
    op.drop_table("sub_score_history")
