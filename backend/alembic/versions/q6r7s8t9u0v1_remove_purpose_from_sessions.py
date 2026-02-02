"""remove_purpose_from_sessions

Remove the deprecated purpose column from sessions table.
Purpose has been replaced by agent_slug for tracking session context.

Revision ID: q6r7s8t9u0v1
Revises: p5q6r7s8t9u0
Create Date: 2026-01-28 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "q6r7s8t9u0v1"
down_revision: str | Sequence[str] | None = "p5q6r7s8t9u0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove purpose column from sessions table."""
    op.drop_index("ix_sessions_purpose", table_name="sessions")
    op.drop_column("sessions", "purpose")


def downgrade() -> None:
    """Restore purpose column to sessions table."""
    op.add_column(
        "sessions",
        sa.Column("purpose", sa.String(length=100), nullable=True),
    )
    op.create_index("ix_sessions_purpose", "sessions", ["purpose"], unique=False)
