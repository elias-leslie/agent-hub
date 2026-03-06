"""add verbosity_level to agents

Revision ID: 6561eb83acff
Revises: 4bc9235ec01b
Create Date: 2026-03-06 08:49:10.134035

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '6561eb83acff'
down_revision: str | Sequence[str] | None = '4bc9235ec01b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add verbosity_level column to agents table."""
    op.add_column("agents", sa.Column("verbosity_level", sa.String(10), nullable=True))


def downgrade() -> None:
    """Remove verbosity_level column from agents table."""
    op.drop_column("agents", "verbosity_level")
