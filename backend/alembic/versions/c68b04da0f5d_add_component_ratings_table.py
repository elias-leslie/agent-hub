"""add_component_ratings_table

Revision ID: c68b04da0f5d
Revises: bd7f1acb476d
Create Date: 2026-02-18 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c68b04da0f5d'
down_revision: str | Sequence[str] | None = 'bd7f1acb476d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create component_ratings table for agent feedback scorecard system."""
    op.create_table(
        'component_ratings',
        sa.Column('id', UUID(as_uuid=False), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('session_id', sa.String(length=36), nullable=False),
        sa.Column('component_id', sa.String(length=50), nullable=False),
        sa.Column('reliability', sa.SmallInteger(), nullable=True),
        sa.Column('clarity', sa.SmallInteger(), nullable=True),
        sa.Column('ergonomics', sa.SmallInteger(), nullable=True),
        sa.Column('integration', sa.SmallInteger(), nullable=True),
        sa.Column('documentation', sa.SmallInteger(), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('project_id', sa.String(length=50), nullable=False),
        sa.Column('agent_slug', sa.String(length=100), nullable=True),
        sa.Column('model_used', sa.String(length=50), nullable=True),
        sa.Column('session_type', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('reliability BETWEEN 1 AND 5', name='ck_component_ratings_reliability'),
        sa.CheckConstraint('clarity BETWEEN 1 AND 5', name='ck_component_ratings_clarity'),
        sa.CheckConstraint('ergonomics BETWEEN 1 AND 5', name='ck_component_ratings_ergonomics'),
        sa.CheckConstraint('integration BETWEEN 1 AND 5', name='ck_component_ratings_integration'),
        sa.CheckConstraint('documentation BETWEEN 1 AND 5', name='ck_component_ratings_documentation'),
    )
    op.create_index('idx_component_ratings_component', 'component_ratings', ['component_id'])
    op.create_index('idx_component_ratings_session', 'component_ratings', ['session_id'])
    op.create_index('idx_component_ratings_project', 'component_ratings', ['project_id'])
    op.create_index('idx_component_ratings_created', 'component_ratings', ['created_at'])


def downgrade() -> None:
    """Drop component_ratings table."""
    op.drop_index('idx_component_ratings_created', table_name='component_ratings')
    op.drop_index('idx_component_ratings_project', table_name='component_ratings')
    op.drop_index('idx_component_ratings_session', table_name='component_ratings')
    op.drop_index('idx_component_ratings_component', table_name='component_ratings')
    op.drop_table('component_ratings')
