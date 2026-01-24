"""drop_mandate_tags_column

Revision ID: h7i8j9k0l1m2
Revises: 78ebdaac1078
Create Date: 2026-01-24 12:00:00.000000

Removes mandate_tags column from agents table.
Mandate injection is now handled via semantic search in the progressive
context system rather than agent-specific tags.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "h7i8j9k0l1m2"
down_revision: str | Sequence[str] | None = "78ebdaac1078"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop mandate_tags column from agents table."""
    op.drop_column("agents", "mandate_tags")


def downgrade() -> None:
    """Restore mandate_tags column to agents table."""
    op.add_column(
        "agents",
        sa.Column("mandate_tags", sa.JSON(), nullable=False, server_default="[]"),
    )
