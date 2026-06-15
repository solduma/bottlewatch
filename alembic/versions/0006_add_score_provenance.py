"""add score provenance columns

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-14

Add `sub_score_provenance` (JSON) and `static_seed_share` (float) to
`scores` so the API and UI can distinguish live-extracted sub-scores
from static research seeds.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scores",
        sa.Column("sub_score_provenance", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "scores",
        sa.Column("static_seed_share", sa.Float(), nullable=False, server_default="0.0"),
    )


def downgrade() -> None:
    op.drop_column("scores", "static_seed_share")
    op.drop_column("scores", "sub_score_provenance")
