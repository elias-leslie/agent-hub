"""add_external_id_to_sessions

Revision ID: c7a82f0e9b12
Revises: ed13ea976211
Create Date: 2026-01-17 10:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7a82f0e9b12"
down_revision: str | Sequence[str] | None = "ed13ea976211"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add external_id column to sessions for cost aggregation."""
    op.add_column("sessions", sa.Column("external_id", sa.String(length=100), nullable=True))
    op.create_index(op.f("ix_sessions_external_id"), "sessions", ["external_id"], unique=False)


def downgrade() -> None:
    """Remove external_id column from sessions."""
    op.drop_index(op.f("ix_sessions_external_id"), table_name="sessions")
    op.drop_column("sessions", "external_id")
