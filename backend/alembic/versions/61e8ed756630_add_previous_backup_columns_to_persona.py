"""add previous backup columns to persona

Revision ID: 61e8ed756630
Revises: 345f14d99f4f
Create Date: 2026-02-27 19:57:56.364398

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '61e8ed756630'
down_revision: str | Sequence[str] | None = '345f14d99f4f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("persona", sa.Column("user_context_previous", sa.Text(), nullable=True))
    op.add_column("persona", sa.Column("heartbeat_instructions_previous", sa.Text(), nullable=True))
    op.add_column("persona", sa.Column("personality_previous", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("persona", "personality_previous")
    op.drop_column("persona", "heartbeat_instructions_previous")
    op.drop_column("persona", "user_context_previous")
