"""merge_heads

Revision ID: 8939a1bd7848
Revises: 98f371912aa2, c7a82f0e9b12
Create Date: 2026-01-17 16:51:25.175094

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "8939a1bd7848"
down_revision: str | Sequence[str] | None = ("98f371912aa2", "c7a82f0e9b12")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
