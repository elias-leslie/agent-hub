"""add_tool_permissions_to_agents

Revision ID: w2x3y4z5a6b7
Revises: v1w2x3y4z5a6
Create Date: 2026-02-01 16:00:00.000000

Adds tool_permissions JSON column to agents table for explicit permission configuration.
Supports PermissionConfig structure: mode, allow_list, deny_list, tool_permissions dict.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "w2x3y4z5a6b7"
down_revision: str | Sequence[str] | None = "v1w2x3y4z5a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add tool_permissions column to agents table."""
    op.add_column(
        "agents",
        sa.Column("tool_permissions", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    """Remove tool_permissions column from agents table."""
    op.drop_column("agents", "tool_permissions")
