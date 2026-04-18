"""add_session_summary_segments

Revision ID: 755848284d1e
Revises: 4d833a3be2d8
Create Date: 2026-02-13 20:30:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '755848284d1e'
down_revision: str | Sequence[str] | None = '4d833a3be2d8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create session_summary_segments table for incremental session summaries."""
    op.create_table(
        'session_summary_segments',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('session_id', sa.String(length=36), nullable=False),
        sa.Column('summary_oneliner', sa.Text(), nullable=False),
        sa.Column('summary_outcome', sa.String(length=20), nullable=True),
        sa.Column('summary_git_digest', sa.Text(), nullable=True),
        sa.Column('summary_branch', sa.String(length=200), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'idx_segments_session_created',
        'session_summary_segments',
        ['session_id', 'created_at'],
    )


def downgrade() -> None:
    """Drop session_summary_segments table."""
    op.drop_index('idx_segments_session_created', table_name='session_summary_segments')
    op.drop_table('session_summary_segments')
