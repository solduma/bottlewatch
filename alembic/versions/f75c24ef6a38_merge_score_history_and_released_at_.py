"""merge score_history and released_at branches

Revision ID: f75c24ef6a38
Revises: 0008, 0005_add_signals_released_at
Create Date: 2026-06-15 21:26:58.599709

"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "f75c24ef6a38"
down_revision: Union[str, Sequence[str], None] = ("0008", "0005_add_signals_released_at")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
