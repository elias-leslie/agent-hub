"""add premium_model_id to agents

Revision ID: 4bc9235ec01b
Revises: 1dd96b677795
Create Date: 2026-03-04 11:03:03.022611

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4bc9235ec01b'
down_revision: Union[str, Sequence[str], None] = '1dd96b677795'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add premium_model_id column for tier-aware model selection."""
    op.add_column("agents", sa.Column("premium_model_id", sa.String(100), nullable=True))


def downgrade() -> None:
    """Remove premium_model_id column."""
    op.drop_column("agents", "premium_model_id")
