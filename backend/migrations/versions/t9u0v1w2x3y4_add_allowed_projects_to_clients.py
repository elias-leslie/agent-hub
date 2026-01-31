"""add_allowed_projects_to_clients

Revision ID: t9u0v1w2x3y4
Revises: s8t9u0v1w2x3
Create Date: 2026-01-30 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "t9u0v1w2x3y4"
down_revision: str | Sequence[str] | None = "s8t9u0v1w2x3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add allowed_projects column to clients table.

    JSON array of allowed project_ids. NULL = unrestricted (internal clients).
    """
    op.add_column(
        "clients",
        sa.Column("allowed_projects", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Remove allowed_projects column from clients table."""
    op.drop_column("clients", "allowed_projects")
