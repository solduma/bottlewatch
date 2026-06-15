"""add normalization_mode to score_history

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-14

Add `normalization_mode` to `score_history` so the backtest can
distinguish fixed-band and rolling-band score histories when it
runs both modes in parallel.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "score_history",
        sa.Column("normalization_mode", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("score_history", "normalization_mode")
