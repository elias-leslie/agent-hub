"""add_claude_code_session_type

Revision ID: b5c6d7e8f9a0
Revises: a84930c276eb
Create Date: 2026-02-06 10:00:00.000000

Adds 'claude_code' value to session_type_enum for CC sessions.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b5c6d7e8f9a0"
down_revision: str | Sequence[str] | None = "a84930c276eb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add 'claude_code' value to session_type_enum."""
    op.execute("ALTER TYPE session_type_enum ADD VALUE IF NOT EXISTS 'claude_code'")


def downgrade() -> None:
    """Cannot remove enum values in PostgreSQL - would need to recreate type."""
    pass
