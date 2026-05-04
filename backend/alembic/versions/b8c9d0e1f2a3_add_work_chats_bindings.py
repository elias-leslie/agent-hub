"""add_work_chats_bindings

Revision ID: b8c9d0e1f2a3
Revises: a7c9d3e5f1b2
Create Date: 2026-05-04 01:05:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: str | Sequence[str] | None = "a7c9d3e5f1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("session_events", sa.Column("transport", sa.String(50), nullable=True))
    op.add_column("session_events", sa.Column("surface", sa.String(100), nullable=True))
    op.add_column("session_events", sa.Column("chat_id", sa.String(100), nullable=True))
    op.add_column("session_events", sa.Column("message_id", sa.String(100), nullable=True))
    op.add_column("session_events", sa.Column("pane_id", sa.String(100), nullable=True))
    op.add_column("session_events", sa.Column("source_client", sa.String(100), nullable=True))

    op.create_table(
        "session_bindings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=False),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("surface", sa.String(100), nullable=False, server_default="work_chats"),
        sa.Column("pane_id", sa.String(100), nullable=True),
        sa.Column("project_id", sa.String(100), nullable=True),
        sa.Column("task_id", sa.String(100), nullable=True),
        sa.Column("feedback_id", sa.String(100), nullable=True),
        sa.Column("design_id", sa.String(100), nullable=True),
        sa.Column("telegram_chat_id", sa.String(100), nullable=True),
        sa.Column("telegram_thread_id", sa.String(100), nullable=True),
        sa.Column("telegram_message_id", sa.String(100), nullable=True),
        sa.Column("source_client", sa.String(100), nullable=True),
        sa.Column("work_context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("surface", "pane_id", name="uq_session_bindings_surface_pane"),
    )
    op.create_index("ix_session_bindings_session_id", "session_bindings", ["session_id"])
    op.create_index("ix_session_bindings_project_id", "session_bindings", ["project_id"])
    op.create_index("ix_session_bindings_task_id", "session_bindings", ["task_id"])
    op.create_index("ix_session_bindings_feedback_id", "session_bindings", ["feedback_id"])
    op.create_index("ix_session_bindings_design_id", "session_bindings", ["design_id"])
    op.create_index("ix_session_bindings_telegram_chat_id", "session_bindings", ["telegram_chat_id"])
    op.create_index("ix_session_bindings_task", "session_bindings", ["project_id", "task_id"])
    op.create_index("ix_session_bindings_telegram", "session_bindings", ["telegram_chat_id", "telegram_thread_id"])

    op.create_table(
        "action_requests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=False),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("request_type", sa.String(50), nullable=False, server_default="blocker"),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("response_content", sa.Text(), nullable=True),
        sa.Column("telegram_chat_id", sa.String(100), nullable=True),
        sa.Column("telegram_thread_id", sa.String(100), nullable=True),
        sa.Column("telegram_message_id", sa.String(100), nullable=True),
        sa.Column("correlation_id", sa.String(100), nullable=True),
        sa.Column("join_code", sa.String(32), nullable=True),
        sa.Column("source_client", sa.String(100), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_action_requests_session_id", "action_requests", ["session_id"])
    op.create_index("ix_action_requests_status", "action_requests", ["status"])
    op.create_index("ix_action_requests_telegram_chat_id", "action_requests", ["telegram_chat_id"])
    op.create_index("ix_action_requests_correlation_id", "action_requests", ["correlation_id"])
    op.create_index("ix_action_requests_join_code", "action_requests", ["join_code"])
    op.create_index("ix_action_requests_session_status", "action_requests", ["session_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_action_requests_session_status", table_name="action_requests")
    op.drop_index("ix_action_requests_join_code", table_name="action_requests")
    op.drop_index("ix_action_requests_correlation_id", table_name="action_requests")
    op.drop_index("ix_action_requests_telegram_chat_id", table_name="action_requests")
    op.drop_index("ix_action_requests_status", table_name="action_requests")
    op.drop_index("ix_action_requests_session_id", table_name="action_requests")
    op.drop_table("action_requests")

    op.drop_index("ix_session_bindings_telegram", table_name="session_bindings")
    op.drop_index("ix_session_bindings_task", table_name="session_bindings")
    op.drop_index("ix_session_bindings_telegram_chat_id", table_name="session_bindings")
    op.drop_index("ix_session_bindings_design_id", table_name="session_bindings")
    op.drop_index("ix_session_bindings_feedback_id", table_name="session_bindings")
    op.drop_index("ix_session_bindings_task_id", table_name="session_bindings")
    op.drop_index("ix_session_bindings_project_id", table_name="session_bindings")
    op.drop_index("ix_session_bindings_session_id", table_name="session_bindings")
    op.drop_table("session_bindings")

    op.drop_column("session_events", "source_client")
    op.drop_column("session_events", "pane_id")
    op.drop_column("session_events", "message_id")
    op.drop_column("session_events", "chat_id")
    op.drop_column("session_events", "surface")
    op.drop_column("session_events", "transport")
