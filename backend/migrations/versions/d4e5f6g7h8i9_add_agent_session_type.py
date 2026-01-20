"""add_agent_session_type

Revision ID: d4e5f6g7h8i9
Revises: c3d4e5f6g7h8
Create Date: 2026-01-20 11:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e5f6g7h8i9"
down_revision: str | Sequence[str] | None = "c3d4e5f6g7h8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add 'agent' value to session_type_enum."""
    # PostgreSQL enum modification
    op.execute("ALTER TYPE session_type_enum ADD VALUE IF NOT EXISTS 'agent'")


def downgrade() -> None:
    """Remove 'agent' value from session_type_enum.

    Note: PostgreSQL doesn't support removing enum values directly.
    This would require creating a new enum type without 'agent' and migrating.
    For simplicity, we leave the value in place on downgrade.
    """
    # Cannot easily remove enum values in PostgreSQL
    pass
