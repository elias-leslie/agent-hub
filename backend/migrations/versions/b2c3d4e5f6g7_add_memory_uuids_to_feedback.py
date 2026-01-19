"""add_memory_uuids_to_feedback

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-01-19 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6g7"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add referenced_rule_uuids column to message_feedback table."""
    op.add_column(
        "message_feedback",
        sa.Column("referenced_rule_uuids", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    """Remove referenced_rule_uuids column from message_feedback table."""
    op.drop_column("message_feedback", "referenced_rule_uuids")
