"""drop_auto_tier_column

Revision ID: 536346caeff9
Revises: dd4ee5ff6aa7
Create Date: 2026-02-24 20:22:00.040311

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '536346caeff9'
down_revision: str | Sequence[str] | None = 'dd4ee5ff6aa7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove auto_tier column from agents table.

    Auto-tier (per-request model routing by complexity) has been replaced
    by Jenny's autonomous model management. No agents use auto_tier=true.
    """
    op.drop_column("agents", "auto_tier")

    # Clean up stale tier preference from user_preferences
    op.execute(sa.text("DELETE FROM user_preferences WHERE key = 'model_tier_preference'"))


def downgrade() -> None:
    """Restore auto_tier column to agents table."""
    op.add_column(
        "agents",
        sa.Column("auto_tier", sa.Boolean(), server_default="false", nullable=False),
    )
