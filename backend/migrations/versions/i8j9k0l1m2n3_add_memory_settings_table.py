"""add_memory_settings_table

Revision ID: i8j9k0l1m2n3
Revises: h7i8j9k0l1m2
Create Date: 2026-01-24 12:00:00.000000

Adds memory_settings table for storing global memory configuration
including token budget limits and enable/disable toggle.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "i8j9k0l1m2n3"
down_revision: str | Sequence[str] | None = "h7i8j9k0l1m2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create memory_settings table with default row."""
    op.create_table(
        "memory_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("total_budget", sa.Integer(), nullable=False, server_default="2000"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # Insert default settings row (singleton pattern)
    op.execute(
        "INSERT INTO memory_settings (id, enabled, total_budget) VALUES (1, true, 2000)"
    )


def downgrade() -> None:
    """Drop memory_settings table."""
    op.drop_table("memory_settings")
