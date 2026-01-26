"""add_tier_change_log_table

Revision ID: k0l1m2n3o4p5
Revises: j9k0l1m2n3o4
Create Date: 2026-01-26 12:00:00.000000

Adds tier_change_log table for auditing episode tier changes.
Tracks promotions, demotions, and the reasons for each change.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "k0l1m2n3o4p5"
down_revision: str | Sequence[str] | None = "j9k0l1m2n3o4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create tier_change_log table for audit trail."""
    op.create_table(
        "tier_change_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("episode_uuid", sa.String(36), nullable=False, index=True),
        sa.Column("old_tier", sa.String(20), nullable=False),
        sa.Column("new_tier", sa.String(20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("change_type", sa.String(20), nullable=False),  # 'promotion' or 'demotion'
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_index("ix_tier_change_log_created_at", "tier_change_log", ["created_at"])


def downgrade() -> None:
    """Drop tier_change_log table."""
    op.drop_index("ix_tier_change_log_created_at", table_name="tier_change_log")
    op.drop_table("tier_change_log")
