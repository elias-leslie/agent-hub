"""add_continuity_settings

Revision ID: e5g6h7i8j9k0
Revises: d4f5a6b7c8d9
Create Date: 2026-02-11 00:00:01.000000

Adds continuity injection settings to memory_settings table:
- continuity_enabled: toggle for Recent Activity block
- continuity_max_tokens: token budget for continuity block
- continuity_max_sessions: max sessions to include
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5g6h7i8j9k0"
down_revision: str | Sequence[str] | None = "d4f5a6b7c8d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add continuity settings columns."""
    op.add_column(
        "memory_settings",
        sa.Column("continuity_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "memory_settings",
        sa.Column("continuity_max_tokens", sa.Integer(), nullable=False, server_default=sa.text("200")),
    )
    op.add_column(
        "memory_settings",
        sa.Column("continuity_max_sessions", sa.Integer(), nullable=False, server_default=sa.text("5")),
    )


def downgrade() -> None:
    """Remove continuity settings columns."""
    op.drop_column("memory_settings", "continuity_max_sessions")
    op.drop_column("memory_settings", "continuity_max_tokens")
    op.drop_column("memory_settings", "continuity_enabled")
