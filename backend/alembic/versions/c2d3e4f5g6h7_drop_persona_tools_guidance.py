"""drop_persona_tools_guidance

Revision ID: c2d3e4f5g6h7
Revises: 31f7c68cf57f
Create Date: 2026-02-23 20:00:00.000000

Drops the tools_guidance column from the persona table.
Content was duplicated by memory mandates/guardrails; unique content
migrated to a pinned mandate episode.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c2d3e4f5g6h7"
down_revision: str | Sequence[str] | None = "31f7c68cf57f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("persona", "tools_guidance")


def downgrade() -> None:
    op.add_column("persona", sa.Column("tools_guidance", sa.Text(), nullable=True))
