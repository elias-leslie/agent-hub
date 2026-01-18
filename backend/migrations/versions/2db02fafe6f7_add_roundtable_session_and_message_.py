"""add_roundtable_session_and_message_tables

Revision ID: 2db02fafe6f7
Revises: 8939a1bd7848
Create Date: 2026-01-18 00:48:20.454284

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2db02fafe6f7"
down_revision: str | Sequence[str] | None = "8939a1bd7848"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create roundtable_sessions table
    op.create_table(
        "roundtable_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(100), nullable=False, index=True),
        sa.Column(
            "mode",
            sa.Enum("quick", "deliberation", name="roundtable_mode"),
            nullable=False,
            server_default="quick",
        ),
        sa.Column(
            "tool_mode",
            sa.Enum("read_only", "yolo", name="roundtable_tool_mode"),
            nullable=False,
            server_default="read_only",
        ),
        sa.Column(
            "status",
            sa.Enum("active", "completed", "failed", name="roundtable_status"),
            nullable=False,
            server_default="active",
        ),
        sa.Column("memory_group_id", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_roundtable_sessions_project_created",
        "roundtable_sessions",
        ["project_id", "created_at"],
    )

    # Create roundtable_messages table
    op.create_table(
        "roundtable_messages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("roundtable_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("agent_type", sa.String(20), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_roundtable_messages_session_created",
        "roundtable_messages",
        ["session_id", "created_at"],
    )
    op.create_index(
        "ix_roundtable_messages_session_agent",
        "roundtable_messages",
        ["session_id", "agent_type"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_roundtable_messages_session_agent", table_name="roundtable_messages")
    op.drop_index("ix_roundtable_messages_session_created", table_name="roundtable_messages")
    op.drop_table("roundtable_messages")

    op.drop_index("ix_roundtable_sessions_project_created", table_name="roundtable_sessions")
    op.drop_table("roundtable_sessions")

    # Drop enums
    op.execute("DROP TYPE IF EXISTS roundtable_status")
    op.execute("DROP TYPE IF EXISTS roundtable_tool_mode")
    op.execute("DROP TYPE IF EXISTS roundtable_mode")
