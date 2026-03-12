"""add session health tracking

Revision ID: e25ac263bac8
Revises: f1a2b3c4d5e6
Create Date: 2026-03-11 20:13:29.205602

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e25ac263bac8'
down_revision: str | Sequence[str] | None = 'f1a2b3c4d5e6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "sessions",
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "sessions",
        sa.Column("health_detail", sa.String(length=100), nullable=True),
    )
    op.create_index(
        "ix_sessions_status_last_activity",
        "sessions",
        ["status", "last_activity_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_sessions_status_last_activity", table_name="sessions")
    op.drop_column("sessions", "health_detail")
    op.drop_column("sessions", "last_activity_at")
