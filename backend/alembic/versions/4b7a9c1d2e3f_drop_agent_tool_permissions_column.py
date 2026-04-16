"""drop_agent_tool_permissions_column

Revision ID: 4b7a9c1d2e3f
Revises: 24ebd21257f3
Create Date: 2026-04-12 21:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4b7a9c1d2e3f"
down_revision: str | Sequence[str] | None = "24ebd21257f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column("agents", "tool_permissions")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        "agents",
        sa.Column("tool_permissions", sa.JSON(), nullable=True),
    )
