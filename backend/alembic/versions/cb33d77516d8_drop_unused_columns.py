"""drop_unused_columns

Revision ID: cb33d77516d8
Revises: w2x3y4z5a6b7
Create Date: 2026-02-02 13:53:31.620406

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cb33d77516d8"
down_revision: str | Sequence[str] | None = "w2x3y4z5a6b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _drop_table_with_indexes(table_name: str, index_names: list[str]) -> None:
    """Drop indexes and table."""
    for idx in index_names:
        op.drop_index(op.f(idx), table_name=table_name)
    op.drop_table(table_name)


def _create_indexes(table_name: str, index_configs: list[tuple[str, list[str], bool]]) -> None:
    """Create multiple indexes on a table."""
    for idx_name, columns, unique in index_configs:
        op.create_index(op.f(idx_name), table_name, columns, unique=unique)


def _timestamp_col(name: str = "created_at") -> sa.Column:
    """Create a standard timestamp column."""
    return sa.Column(
        name, postgresql.TIMESTAMP(timezone=True), server_default=sa.text("now()"), autoincrement=False, nullable=False
    )


def _int_pk_col() -> sa.Column:
    """Create a standard integer primary key column."""
    return sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False)


def upgrade() -> None:
    """Upgrade schema."""
    tables_to_drop = [
        ("roundtable_messages", ["ix_roundtable_messages_session_agent", "ix_roundtable_messages_session_created"]),
        ("roundtable_sessions", ["ix_roundtable_sessions_project_created", "ix_roundtable_sessions_project_id"]),
        ("tier_change_log", ["ix_tier_change_log_created_at", "ix_tier_change_log_episode_uuid"]),
        ("message_feedback", ["ix_message_feedback_message", "ix_message_feedback_message_id", "ix_message_feedback_session", "ix_message_feedback_type"]),
        ("global_instructions", ["ix_global_instructions_scope"]),
        ("user_preferences", ["ix_user_preferences_user_id"]),
    ]
    for table, indexes in tables_to_drop:
        _drop_table_with_indexes(table, indexes)
    op.drop_column("memory_settings", "max_references")
    op.drop_constraint(op.f("request_logs_session_id_fkey"), "request_logs", type_="foreignkey")
    op.create_index(op.f("ix_sessions_parent_session_id"), "sessions", ["parent_session_id"], unique=False)
    op.drop_column("sessions", "task_outcome")
    op.drop_column("webhook_subscriptions", "last_triggered_at")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        "webhook_subscriptions",
        sa.Column("last_triggered_at", postgresql.TIMESTAMP(timezone=True), autoincrement=False, nullable=True),
    )
    op.add_column(
        "sessions",
        sa.Column(
            "task_outcome", postgresql.ENUM("passed", "failed", name="task_outcome_enum"), autoincrement=False, nullable=True
        ),
    )
    op.drop_index(op.f("ix_sessions_parent_session_id"), table_name="sessions")
    op.create_foreign_key(
        op.f("request_logs_session_id_fkey"), "request_logs", "sessions", ["session_id"], ["id"], ondelete="CASCADE"
    )
    op.add_column(
        "memory_settings",
        sa.Column("max_references", sa.INTEGER(), server_default=sa.text("0"), autoincrement=False, nullable=False),
    )
    op.create_table(
        "user_preferences",
        _int_pk_col(),
        sa.Column("user_id", sa.VARCHAR(length=100), autoincrement=False, nullable=False),
        sa.Column("verbosity", postgresql.ENUM("concise", "normal", "detailed", name="verbosity_level"), autoincrement=False, nullable=False),
        sa.Column("tone", postgresql.ENUM("professional", "friendly", "technical", name="tone_type"), autoincrement=False, nullable=False),
        sa.Column("default_model", sa.VARCHAR(length=100), autoincrement=False, nullable=False),
        _timestamp_col("created_at"),
        _timestamp_col("updated_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("user_preferences_pkey")),
    )
    _create_indexes("user_preferences", [("ix_user_preferences_user_id", ["user_id"], True)])
    op.create_table(
        "global_instructions",
        _int_pk_col(),
        sa.Column("scope", sa.VARCHAR(length=100), autoincrement=False, nullable=False),
        sa.Column("content", sa.TEXT(), server_default=sa.text("''::text"), autoincrement=False, nullable=False),
        sa.Column("enabled", sa.BOOLEAN(), server_default=sa.text("true"), autoincrement=False, nullable=False),
        _timestamp_col("created_at"),
        _timestamp_col("updated_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("global_instructions_pkey")),
    )
    _create_indexes("global_instructions", [("ix_global_instructions_scope", ["scope"], True)])

    op.create_table(
        "message_feedback",
        _int_pk_col(),
        sa.Column("message_id", sa.VARCHAR(length=100), autoincrement=False, nullable=False),
        sa.Column("session_id", sa.VARCHAR(length=36), autoincrement=False, nullable=True),
        sa.Column("feedback_type", postgresql.ENUM("positive", "negative", name="feedback_type"), autoincrement=False, nullable=False),
        sa.Column("category", sa.VARCHAR(length=50), autoincrement=False, nullable=True),
        sa.Column("details", sa.TEXT(), autoincrement=False, nullable=True),
        _timestamp_col("created_at"),
        sa.Column("referenced_rule_uuids", postgresql.JSON(astext_type=sa.Text()), autoincrement=False, nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], name=op.f("message_feedback_session_id_fkey"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("message_feedback_pkey")),
    )
    _create_indexes(
        "message_feedback",
        [("ix_message_feedback_type", ["feedback_type"], False), ("ix_message_feedback_session", ["session_id"], False), ("ix_message_feedback_message_id", ["message_id"], False), ("ix_message_feedback_message", ["message_id"], False)],
    )
    op.create_table(
        "tier_change_log",
        _int_pk_col(),
        sa.Column("episode_uuid", sa.VARCHAR(length=36), autoincrement=False, nullable=False),
        sa.Column("old_tier", sa.VARCHAR(length=20), autoincrement=False, nullable=False),
        sa.Column("new_tier", sa.VARCHAR(length=20), autoincrement=False, nullable=False),
        sa.Column("reason", sa.TEXT(), autoincrement=False, nullable=False),
        sa.Column("change_type", sa.VARCHAR(length=20), autoincrement=False, nullable=False),
        _timestamp_col("created_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("tier_change_log_pkey")),
    )
    _create_indexes("tier_change_log", [("ix_tier_change_log_episode_uuid", ["episode_uuid"], False), ("ix_tier_change_log_created_at", ["created_at"], False)])

    op.create_table(
        "roundtable_sessions",
        sa.Column("id", sa.VARCHAR(length=36), autoincrement=False, nullable=False),
        sa.Column("project_id", sa.VARCHAR(length=100), autoincrement=False, nullable=False),
        sa.Column("mode", postgresql.ENUM("quick", "deliberation", name="roundtable_mode"), server_default=sa.text("'quick'::roundtable_mode"), autoincrement=False, nullable=False),
        sa.Column("tool_mode", postgresql.ENUM("read_only", "yolo", name="roundtable_tool_mode"), server_default=sa.text("'read_only'::roundtable_tool_mode"), autoincrement=False, nullable=False),
        sa.Column("status", postgresql.ENUM("active", "completed", "failed", name="roundtable_status"), server_default=sa.text("'active'::roundtable_status"), autoincrement=False, nullable=False),
        sa.Column("memory_group_id", sa.VARCHAR(length=100), autoincrement=False, nullable=True),
        _timestamp_col("created_at"),
        _timestamp_col("updated_at"),
        sa.PrimaryKeyConstraint("id", name="roundtable_sessions_pkey"),
        postgresql_ignore_search_path=False,
    )
    _create_indexes("roundtable_sessions", [("ix_roundtable_sessions_project_id", ["project_id"], False), ("ix_roundtable_sessions_project_created", ["project_id", "created_at"], False)])
    op.create_table(
        "roundtable_messages",
        _int_pk_col(),
        sa.Column("session_id", sa.VARCHAR(length=36), autoincrement=False, nullable=False),
        sa.Column("role", sa.VARCHAR(length=20), autoincrement=False, nullable=False),
        sa.Column("agent_type", sa.VARCHAR(length=20), autoincrement=False, nullable=True),
        sa.Column("content", sa.TEXT(), autoincrement=False, nullable=False),
        sa.Column("tokens", sa.INTEGER(), autoincrement=False, nullable=True),
        sa.Column("model", sa.VARCHAR(length=100), autoincrement=False, nullable=True),
        _timestamp_col("created_at"),
        sa.ForeignKeyConstraint(["session_id"], ["roundtable_sessions.id"], name=op.f("roundtable_messages_session_id_fkey"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("roundtable_messages_pkey")),
    )
    _create_indexes("roundtable_messages", [("ix_roundtable_messages_session_created", ["session_id", "created_at"], False), ("ix_roundtable_messages_session_agent", ["session_id", "agent_type"], False)])
