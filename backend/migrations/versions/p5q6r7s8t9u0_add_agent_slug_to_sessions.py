"""add_agent_slug_to_sessions

Add agent_slug column to sessions table to track which agent processed the session.

Revision ID: p5q6r7s8t9u0
Revises: o4p5q6r7s8t9
Create Date: 2026-01-28 19:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "p5q6r7s8t9u0"
down_revision: str | Sequence[str] | None = "o4p5q6r7s8t9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add agent_slug column to sessions table."""
    op.add_column(
        "sessions",
        sa.Column("agent_slug", sa.String(length=50), nullable=True),
    )
    op.create_index("ix_sessions_agent_slug", "sessions", ["agent_slug"], unique=False)


def downgrade() -> None:
    """Remove agent_slug column from sessions table."""
    op.drop_index("ix_sessions_agent_slug", table_name="sessions")
    op.drop_column("sessions", "agent_slug")
