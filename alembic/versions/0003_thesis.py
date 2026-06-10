"""thesis table (M3)

Revision ID: 0003_thesis
Revises: 0002_scores
Create Date: 2026-06-04

User-authored thesis notes for the override-audit-trail on the
hard guard. One row per (segment, ticker, side). Markdown body
stored as TEXT to keep the DB readable and the round-trip simple.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0003_thesis"
down_revision = "0002_scores"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "thesis",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("segment", sa.String(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=True),
        sa.Column("side", sa.String(), nullable=True),
        sa.Column("body_md", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_thesis_segment", "thesis", ["segment"])
    op.create_index("ix_thesis_ticker", "thesis", ["ticker"])


def downgrade() -> None:
    op.drop_index("ix_thesis_ticker", table_name="thesis")
    op.drop_index("ix_thesis_segment", table_name="thesis")
    op.drop_table("thesis")
