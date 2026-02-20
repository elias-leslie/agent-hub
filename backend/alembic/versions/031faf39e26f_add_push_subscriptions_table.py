"""add push_subscriptions table

Revision ID: 031faf39e26f
Revises: z3a4b5c6d7e8
Create Date: 2026-02-19 22:46:11.392912

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '031faf39e26f'
down_revision: str | Sequence[str] | None = 'z3a4b5c6d7e8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add push_subscriptions table for shared Web Push service."""
    op.create_table('push_subscriptions',
        sa.Column('id', sa.String(length=8), nullable=False),
        sa.Column('endpoint', sa.Text(), nullable=False),
        sa.Column('p256dh_key', sa.Text(), nullable=False),
        sa.Column('auth_key', sa.Text(), nullable=False),
        sa.Column('user_email', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_push_subscriptions')),
        sa.UniqueConstraint('endpoint', name=op.f('uq_push_subscriptions_endpoint'))
    )


def downgrade() -> None:
    """Remove push_subscriptions table."""
    op.drop_table('push_subscriptions')
