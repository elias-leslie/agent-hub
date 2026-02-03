"""add_session_events_table_and_drop_messages

Revision ID: x1y2z3a4b5c6
Revises: s8t9u0v1w2x3
Create Date: 2026-02-02 10:00:00.000000

Creates unified session_events table for full observability.
Drops messages table (user approved data purge).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "x1y2z3a4b5c6"
down_revision: str | Sequence[str] | None = "73c82f4ebcc5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create session_events table and drop messages."""
    op.create_table(
        "session_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=False),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("turn", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("role", sa.String(20), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("tool_name", sa.String(255), nullable=True),
        sa.Column("tool_input", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("tool_output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("tokens", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("model_used", sa.String(100), nullable=True),
        sa.Column("agent_id", sa.String(100), nullable=True),
        sa.Column("agent_name", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            name="fk_session_events_session_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "turn", "sequence", name="uq_session_turn_sequence"),
    )

    op.create_index(
        "ix_session_events_session_turn",
        "session_events",
        ["session_id", "turn", "sequence"],
    )
    op.create_index("ix_session_events_type", "session_events", ["event_type"])
    op.create_index("ix_session_events_tool", "session_events", ["tool_name"])

    op.drop_table("messages")


def downgrade() -> None:
    """Recreate messages table and drop session_events."""
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=True),
        sa.Column("agent_id", sa.String(100), nullable=True),
        sa.Column("agent_name", sa.String(100), nullable=True),
        sa.Column("model_used", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["sessions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_messages_session_created", "messages", ["session_id", "created_at"])
    op.create_index("ix_messages_session_agent", "messages", ["session_id", "agent_id"])
    op.create_index("ix_messages_agent_id", "messages", ["agent_id"])

    op.drop_index("ix_session_events_tool", table_name="session_events")
    op.drop_index("ix_session_events_type", table_name="session_events")
    op.drop_index("ix_session_events_session_turn", table_name="session_events")
    op.drop_table("session_events")
