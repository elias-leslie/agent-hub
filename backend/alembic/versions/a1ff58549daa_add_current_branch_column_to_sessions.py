"""Add current_branch column to sessions

Revision ID: a1ff58549daa
Revises: eb3f732bc0d0
Create Date: 2026-02-16 11:14:55.476754

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1ff58549daa'
down_revision: str | Sequence[str] | None = 'eb3f732bc0d0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add current_branch column for continuity scoping on session close."""
    op.add_column('sessions', sa.Column('current_branch', sa.String(length=200), nullable=True))


def downgrade() -> None:
    """Remove current_branch column."""
    op.drop_column('sessions', 'current_branch')
