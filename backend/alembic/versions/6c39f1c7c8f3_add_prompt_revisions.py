"""add prompt revisions

Revision ID: 6c39f1c7c8f3
Revises: 29e5dc2c0921
Create Date: 2026-03-11 13:08:43.476674

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '6c39f1c7c8f3'
down_revision: Union[str, Sequence[str], None] = '29e5dc2c0921'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "prompt_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("prompt_id", sa.Integer(), sa.ForeignKey("prompts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("prompt_slug", sa.String(length=100), nullable=False),
        sa.Column("prompt_name", sa.String(length=200), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_global", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("exclude_agents", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("changed_by", sa.String(length=100), nullable=True),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_prompt_revisions_prompt_slug", "prompt_revisions", ["prompt_slug"])
    op.create_index("ix_prompt_revisions_action", "prompt_revisions", ["action"])
    op.create_index("ix_prompt_revisions_prompt_id", "prompt_revisions", ["prompt_id"])
    op.create_index(
        "ix_prompt_revisions_prompt_slug_created",
        "prompt_revisions",
        ["prompt_slug", "created_at"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_prompt_revisions_prompt_slug_created", table_name="prompt_revisions")
    op.drop_index("ix_prompt_revisions_prompt_id", table_name="prompt_revisions")
    op.drop_index("ix_prompt_revisions_action", table_name="prompt_revisions")
    op.drop_index("ix_prompt_revisions_prompt_slug", table_name="prompt_revisions")
    op.drop_table("prompt_revisions")
