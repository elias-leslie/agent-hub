"""add_is_coding_agent_to_agents

Revision ID: u0v1w2x3y4z5
Revises: t9u0v1w2x3y4
Create Date: 2026-02-01 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "u0v1w2x3y4z5"
down_revision: str | Sequence[str] | None = "t9u0v1w2x3y4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add is_coding_agent column to agents table."""
    op.add_column(
        "agents",
        sa.Column("is_coding_agent", sa.Boolean(), nullable=False, server_default="false"),
    )
    # Set existing coding agents to True
    op.execute(
        "UPDATE agents SET is_coding_agent = true WHERE slug IN ('coder', 'refactor', 'worker', 'supervisor')"
    )


def downgrade() -> None:
    """Remove is_coding_agent column from agents table."""
    op.drop_column("agents", "is_coding_agent")
