"""add_tool_tracking_columns

Add agent_slug and tool_type columns to request_logs for unified tool/API metrics.

Revision ID: n3o4p5q6r7s8
Revises: m2n3o4p5q6r7
Create Date: 2026-01-28 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "n3o4p5q6r7s8"
down_revision: str | Sequence[str] | None = "m2n3o4p5q6r7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add agent_slug and tool_type columns to request_logs."""
    # Create the enum type first
    tool_type_enum = sa.Enum("api", "cli", "sdk", name="tool_type_enum")
    tool_type_enum.create(op.get_bind(), checkfirst=True)

    # Add agent_slug column
    op.add_column(
        "request_logs",
        sa.Column("agent_slug", sa.String(length=50), nullable=True),
    )
    op.create_index("ix_request_logs_agent_slug", "request_logs", ["agent_slug"], unique=False)

    # Add tool_type column with default 'api'
    op.add_column(
        "request_logs",
        sa.Column(
            "tool_type",
            tool_type_enum,
            nullable=False,
            server_default="api",
        ),
    )


def downgrade() -> None:
    """Remove agent_slug and tool_type columns from request_logs."""
    op.drop_column("request_logs", "tool_type")
    op.drop_index("ix_request_logs_agent_slug", table_name="request_logs")
    op.drop_column("request_logs", "agent_slug")

    # Drop the enum type
    tool_type_enum = sa.Enum("api", "cli", "sdk", name="tool_type_enum")
    tool_type_enum.drop(op.get_bind(), checkfirst=True)
