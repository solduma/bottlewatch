"""add released_at to signals

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-14

Add `released_at` to `signals` so historical recomputes can gate on
the date a data point was actually available, falling back to
`ingested_at` when no release date is supplied.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0005_add_signals_released_at"
down_revision = "0004_score_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "signals",
        sa.Column("released_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("signals", "released_at")
