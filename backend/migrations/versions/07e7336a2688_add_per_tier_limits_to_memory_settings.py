"""add_per_tier_limits_to_memory_settings

Revision ID: 07e7336a2688
Revises: r7s8t9u0v1w2
Create Date: 2026-01-29 12:50:23.855813

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '07e7336a2688'
down_revision: Union[str, Sequence[str], None] = 'r7s8t9u0v1w2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add per-tier limit columns to memory_settings."""
    op.add_column('memory_settings', sa.Column('max_mandates', sa.Integer(), server_default='0', nullable=False))
    op.add_column('memory_settings', sa.Column('max_guardrails', sa.Integer(), server_default='0', nullable=False))
    op.add_column('memory_settings', sa.Column('max_references', sa.Integer(), server_default='0', nullable=False))


def downgrade() -> None:
    """Remove per-tier limit columns from memory_settings."""
    op.drop_column('memory_settings', 'max_references')
    op.drop_column('memory_settings', 'max_guardrails')
    op.drop_column('memory_settings', 'max_mandates')
