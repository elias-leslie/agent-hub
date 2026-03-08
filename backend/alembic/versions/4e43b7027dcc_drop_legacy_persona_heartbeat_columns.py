"""drop legacy persona heartbeat columns

Revision ID: 4e43b7027dcc
Revises: c6d7e8f9a0b1
Create Date: 2026-03-08 11:54:55.822557

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '4e43b7027dcc'
down_revision: str | Sequence[str] | None = 'c6d7e8f9a0b1'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column("persona", "heartbeat_instructions_previous")
    op.drop_column("persona", "heartbeat_instructions")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column("persona", sa.Column("heartbeat_instructions", sa.Text(), nullable=True))
    op.add_column("persona", sa.Column("heartbeat_instructions_previous", sa.Text(), nullable=True))
