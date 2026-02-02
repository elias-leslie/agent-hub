"""add_reference_index_enabled_to_memory_settings

Revision ID: s8t9u0v1w2x3
Revises: 07e7336a2688
Create Date: 2026-01-29 15:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "s8t9u0v1w2x3"
down_revision: str | Sequence[str] | None = "07e7336a2688"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add reference_index_enabled column to memory_settings."""
    op.add_column(
        "memory_settings",
        sa.Column("reference_index_enabled", sa.Boolean(), server_default="true", nullable=False),
    )


def downgrade() -> None:
    """Remove reference_index_enabled column from memory_settings."""
    op.drop_column("memory_settings", "reference_index_enabled")
