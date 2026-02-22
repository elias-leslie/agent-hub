"""rename_soul_to_personality

Revision ID: b3c4d5e6f7g8
Revises: a2b3c4d5e6f7
Create Date: 2026-02-21 22:00:00.000000

Renames persona.soul → persona.personality and adds new persona columns:
heartbeat_instructions, user_context, tools_guidance, onboarding_complete.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b3c4d5e6f7g8"
down_revision: str | Sequence[str] | None = "a2b3c4d5e6f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Rename soul → personality
    op.alter_column("persona", "soul", new_column_name="personality")

    # 2. Add new persona document columns
    op.add_column("persona", sa.Column("heartbeat_instructions", sa.Text(), nullable=True))
    op.add_column("persona", sa.Column("user_context", sa.Text(), nullable=True))
    op.add_column("persona", sa.Column("tools_guidance", sa.Text(), nullable=True))
    op.add_column(
        "persona",
        sa.Column("onboarding_complete", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("persona", "onboarding_complete")
    op.drop_column("persona", "tools_guidance")
    op.drop_column("persona", "user_context")
    op.drop_column("persona", "heartbeat_instructions")
    op.alter_column("persona", "personality", new_column_name="soul")
