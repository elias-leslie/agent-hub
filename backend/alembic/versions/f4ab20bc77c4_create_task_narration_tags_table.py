"""create task narration tags table

Revision ID: f4ab20bc77c4
Revises: d60cd02141c5
Create Date: 2026-03-19 13:44:52.712279

Adds task_narration_tags table for storing [[P:type:content]] progress tags
emitted by agents during task execution.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f4ab20bc77c4"
down_revision: str | Sequence[str] | None = "d60cd02141c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create task_narration_tags table."""
    op.create_table(
        "task_narration_tags",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.String(100), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("tag_type", sa.String(30), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name="fk_task_narration_tags_sessions_session_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_task_narration_tags"),
    )
    op.create_index(
        "ix_narration_tags_task_created",
        "task_narration_tags",
        ["task_id", "created_at"],
    )
    op.create_index(
        "ix_narration_tags_session",
        "task_narration_tags",
        ["session_id"],
    )
    op.create_index(
        "ix_narration_tags_type",
        "task_narration_tags",
        ["tag_type"],
    )


def downgrade() -> None:
    """Drop task_narration_tags table."""
    op.drop_index("ix_narration_tags_type", table_name="task_narration_tags")
    op.drop_index("ix_narration_tags_session", table_name="task_narration_tags")
    op.drop_index("ix_narration_tags_task_created", table_name="task_narration_tags")
    op.drop_table("task_narration_tags")
