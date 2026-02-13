"""add_user_preferences_table

Revision ID: 4d833a3be2d8
Revises: y2z3a4b5c6d7
Create Date: 2026-02-13 10:01:27.945936

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '4d833a3be2d8'
down_revision: str | Sequence[str] | None = 'y2z3a4b5c6d7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'user_preferences',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('value', sa.String(length=500), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_user_preferences_key', 'user_preferences', ['key'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_user_preferences_key', table_name='user_preferences')
    op.drop_table('user_preferences')
