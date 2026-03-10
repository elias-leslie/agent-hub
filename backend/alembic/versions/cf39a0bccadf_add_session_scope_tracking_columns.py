"""add session scope tracking columns

Revision ID: cf39a0bccadf
Revises: b4c5d6e7f8g9
Create Date: 2026-03-10 09:28:56.413832

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cf39a0bccadf"
down_revision: str | Sequence[str] | None = "b4c5d6e7f8g9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("sessions", sa.Column("declared_scope_paths", sa.JSON(), nullable=True))
    op.add_column("sessions", sa.Column("observed_read_paths", sa.JSON(), nullable=True))
    op.add_column("sessions", sa.Column("observed_write_paths", sa.JSON(), nullable=True))
    op.add_column("sessions", sa.Column("scope_confidence", sa.String(length=32), nullable=True))
    op.add_column("sessions", sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_sessions_project_heartbeat",
        "sessions",
        ["project_id", "last_heartbeat_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_sessions_project_heartbeat", table_name="sessions")
    op.drop_column("sessions", "last_heartbeat_at")
    op.drop_column("sessions", "scope_confidence")
    op.drop_column("sessions", "observed_write_paths")
    op.drop_column("sessions", "observed_read_paths")
    op.drop_column("sessions", "declared_scope_paths")
