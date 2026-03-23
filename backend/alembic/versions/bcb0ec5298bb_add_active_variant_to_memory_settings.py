"""add active variant to memory settings

Revision ID: bcb0ec5298bb
Revises: f4ab20bc77c4
Create Date: 2026-03-22 02:42:17.114771

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bcb0ec5298bb"
down_revision: str | Sequence[str] | None = "f4ab20bc77c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add active_variant column to memory_settings."""
    op.add_column(
        "memory_settings",
        sa.Column("active_variant", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    """Remove active_variant column from memory_settings."""
    op.drop_column("memory_settings", "active_variant")
