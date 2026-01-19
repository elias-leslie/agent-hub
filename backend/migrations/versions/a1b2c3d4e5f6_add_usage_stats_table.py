"""add_usage_stats_table

Revision ID: a1b2c3d4e5f6
Revises: 2db02fafe6f7
Create Date: 2026-01-19 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "2db02fafe6f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create usage_stats table for historical memory usage tracking."""
    op.create_table(
        "usage_stats",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("episode_uuid", sa.String(36), nullable=False),
        sa.Column(
            "metric_type",
            sa.Enum("loaded", "referenced", "success", name="usage_metric_type"),
            nullable=False,
        ),
        sa.Column("value", sa.Integer(), nullable=False, default=1),
        sa.Column("timestamp", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_usage_stats_episode_uuid", "usage_stats", ["episode_uuid"])
    op.create_index("ix_usage_stats_timestamp", "usage_stats", ["timestamp"])
    op.create_index(
        "ix_usage_stats_episode_metric", "usage_stats", ["episode_uuid", "metric_type"]
    )


def downgrade() -> None:
    """Drop usage_stats table."""
    op.drop_index("ix_usage_stats_episode_metric", table_name="usage_stats")
    op.drop_index("ix_usage_stats_timestamp", table_name="usage_stats")
    op.drop_index("ix_usage_stats_episode_uuid", table_name="usage_stats")
    op.drop_table("usage_stats")
    op.execute("DROP TYPE IF EXISTS usage_metric_type")
