"""drop premium model from agents

Revision ID: 6996cae6424b
Revises: 356c591a71de
Create Date: 2026-03-07 23:03:04.457244

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6996cae6424b'
down_revision: Union[str, Sequence[str], None] = '356c591a71de'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column("agents", "premium_model_id")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column("agents", sa.Column("premium_model_id", sa.String(length=100), nullable=True))
