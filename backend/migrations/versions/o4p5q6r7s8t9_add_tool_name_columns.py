"""add_tool_name_columns

Add tool_name and source_path columns to request_logs for granular tool tracking.

- tool_name: Specific command/method (e.g., 'st complete', 'client.complete')
- source_path: Caller file path (for SDK debugging)

Revision ID: o4p5q6r7s8t9
Revises: n3o4p5q6r7s8
Create Date: 2026-01-28 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "o4p5q6r7s8t9"
down_revision: str | Sequence[str] | None = "n3o4p5q6r7s8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add tool_name and source_path columns to request_logs."""
    # Add tool_name column - specific command/method name
    op.add_column(
        "request_logs",
        sa.Column("tool_name", sa.String(length=100), nullable=True),
    )
    op.create_index("ix_request_logs_tool_name", "request_logs", ["tool_name"], unique=False)

    # Add source_path column - caller file path for debugging
    op.add_column(
        "request_logs",
        sa.Column("source_path", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    """Remove tool_name and source_path columns from request_logs."""
    op.drop_column("request_logs", "source_path")
    op.drop_index("ix_request_logs_tool_name", table_name="request_logs")
    op.drop_column("request_logs", "tool_name")
