"""drop_continuity_max_tokens

Revision ID: f6h7i8j9k0l1
Revises: e5g6h7i8j9k0
Create Date: 2026-02-11 00:00:02.000000

Removes continuity_max_tokens from memory_settings — token budget is
managed by the shared total_budget, not a per-feature limit.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f6h7i8j9k0l1"
down_revision: str | Sequence[str] | None = "e5g6h7i8j9k0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop continuity_max_tokens column."""
    op.drop_column("memory_settings", "continuity_max_tokens")


def downgrade() -> None:
    """Re-add continuity_max_tokens column."""
    op.add_column(
        "memory_settings",
        sa.Column("continuity_max_tokens", sa.Integer(), nullable=False, server_default=sa.text("200")),
    )
