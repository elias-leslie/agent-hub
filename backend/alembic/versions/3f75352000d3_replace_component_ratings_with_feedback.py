"""replace_component_ratings_with_feedback

Revision ID: 3f75352000d3
Revises: c68b04da0f5d
Create Date: 2026-02-18 14:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '3f75352000d3'
down_revision: str | Sequence[str] | None = 'c68b04da0f5d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop component_ratings and create feedback_items + feedback_votes."""
    # Drop old table (0 rows, Phase 1 artifact)
    op.drop_index('idx_component_ratings_created', table_name='component_ratings')
    op.drop_index('idx_component_ratings_project', table_name='component_ratings')
    op.drop_index('idx_component_ratings_session', table_name='component_ratings')
    op.drop_index('idx_component_ratings_component', table_name='component_ratings')
    op.drop_table('component_ratings')

    # Create feedback_items
    op.create_table(
        'feedback_items',
        sa.Column('id', UUID(as_uuid=False), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('component_id', sa.String(length=50), nullable=False),
        sa.Column('feedback_type', sa.String(length=20), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('severity', sa.String(length=10), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='open', nullable=False),
        sa.Column('project_id', sa.String(length=50), nullable=False),
        sa.Column('created_by_session_id', sa.String(length=36), nullable=True),
        sa.Column('agent_slug', sa.String(length=100), nullable=True),
        sa.Column('model_used', sa.String(length=50), nullable=True),
        sa.Column('session_type', sa.String(length=50), nullable=True),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('resolution_note', sa.Text(), nullable=True),
        sa.Column('vote_count', sa.Integer(), server_default='1', nullable=False),
        sa.Column('linked_task_id', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['created_by_session_id'], ['sessions.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint(
            "feedback_type IN ('friction', 'idea', 'improvement', 'praise')",
            name='ck_feedback_items_type',
        ),
        sa.CheckConstraint(
            "status IN ('open', 'acknowledged', 'resolved', 'wont_fix')",
            name='ck_feedback_items_status',
        ),
    )

    # Add tsvector column via raw SQL (SQLAlchemy doesn't support GENERATED ALWAYS AS for tsvector)
    op.execute("""
        ALTER TABLE feedback_items ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (
            to_tsvector('english', coalesce(title, '') || ' ' || coalesce(description, ''))
        ) STORED
    """)

    # Indexes for feedback_items
    op.create_index('idx_feedback_items_component', 'feedback_items', ['component_id'])
    op.create_index('idx_feedback_items_type', 'feedback_items', ['feedback_type'])
    op.create_index('idx_feedback_items_status', 'feedback_items', ['status'])
    op.create_index('idx_feedback_items_project', 'feedback_items', ['project_id'])
    op.execute('CREATE INDEX idx_feedback_items_votes ON feedback_items(vote_count DESC)')
    op.create_index('idx_feedback_items_created', 'feedback_items', ['created_at'])
    op.create_index('idx_feedback_items_search', 'feedback_items', ['search_vector'], postgresql_using='gin')

    # Create feedback_votes
    op.create_table(
        'feedback_votes',
        sa.Column('id', UUID(as_uuid=False), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('feedback_item_id', UUID(as_uuid=False), nullable=False),
        sa.Column('session_id', sa.String(length=36), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('agent_slug', sa.String(length=100), nullable=True),
        sa.Column('model_used', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['feedback_item_id'], ['feedback_items.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('feedback_item_id', 'session_id', name='uq_feedback_votes_item_session'),
    )

    # Indexes for feedback_votes
    op.create_index('idx_feedback_votes_item', 'feedback_votes', ['feedback_item_id'])
    op.create_index('idx_feedback_votes_session', 'feedback_votes', ['session_id'])


def downgrade() -> None:
    """Drop feedback tables and restore component_ratings."""
    # Drop feedback_votes
    op.drop_index('idx_feedback_votes_session', table_name='feedback_votes')
    op.drop_index('idx_feedback_votes_item', table_name='feedback_votes')
    op.drop_table('feedback_votes')

    # Drop feedback_items
    op.drop_index('idx_feedback_items_search', table_name='feedback_items')
    op.drop_index('idx_feedback_items_created', table_name='feedback_items')
    op.drop_index('idx_feedback_items_votes', table_name='feedback_items')
    op.drop_index('idx_feedback_items_project', table_name='feedback_items')
    op.drop_index('idx_feedback_items_status', table_name='feedback_items')
    op.drop_index('idx_feedback_items_type', table_name='feedback_items')
    op.drop_index('idx_feedback_items_component', table_name='feedback_items')
    op.drop_table('feedback_items')

    # Restore component_ratings
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
