"""add exclude_agents to prompts

Revision ID: e2a476ce0825
Revises: 61e8ed756630
Create Date: 2026-02-28 09:21:15.474854

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e2a476ce0825'
down_revision: str | Sequence[str] | None = '61e8ed756630'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "prompts",
        sa.Column(
            "exclude_agents",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("prompts", "exclude_agents")
