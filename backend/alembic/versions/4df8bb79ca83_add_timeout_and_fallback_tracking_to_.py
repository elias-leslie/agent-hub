"""add timeout and fallback tracking to request_logs

Revision ID: 4df8bb79ca83
Revises: c8113ded1ed2
Create Date: 2026-03-01 15:10:28.949582

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4df8bb79ca83'
down_revision: Union[str, Sequence[str], None] = 'c8113ded1ed2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add timeout/fallback tracking columns to request_logs and timeout to agents."""
    op.add_column("request_logs", sa.Column("timed_out", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("request_logs", sa.Column("used_fallback", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("request_logs", sa.Column("fallback_model", sa.String(100), nullable=True))
    op.add_column("agents", sa.Column("timeout_seconds", sa.Float(), nullable=True))


def downgrade() -> None:
    """Remove timeout/fallback tracking columns."""
    op.drop_column("agents", "timeout_seconds")
    op.drop_column("request_logs", "fallback_model")
    op.drop_column("request_logs", "used_fallback")
    op.drop_column("request_logs", "timed_out")
