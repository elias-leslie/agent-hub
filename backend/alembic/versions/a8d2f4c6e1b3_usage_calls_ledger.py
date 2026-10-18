"""add usage_calls and usage_sessions

Revision ID: a8d2f4c6e1b3
Revises: f3c9a1d7b5e2
Create Date: 2026-10-18 14:30:00.000000

Per-call ledger for Claude Code and Codex transcript usage (sub-agents included), priced at
API list price, plus one identity row per session and sub-agent (project, kind, routine job).
The subscription usage collector fills both; existing transcripts are replayed once.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a8d2f4c6e1b3"
down_revision: str | Sequence[str] | None = "f3c9a1d7b5e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "usage_calls",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("call_key", sa.String(200), nullable=False, unique=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("session_id", sa.String(100), nullable=False),
        sa.Column("agent_id", sa.String(100), nullable=False, server_default=""),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("cached_input_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("cache_write_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("api_equiv_usd", sa.Float(), nullable=True),
    )
    op.create_index("ix_usage_calls_occurred_at", "usage_calls", ["occurred_at"])
    op.create_index("ix_usage_calls_session_occurred", "usage_calls", ["session_id", "occurred_at"])
    op.create_index("ix_usage_calls_agent", "usage_calls", ["agent_id"], postgresql_where=sa.text("agent_id <> ''"))
    op.create_table(
        "usage_sessions",
        sa.Column("provider", sa.String(20), primary_key=True),
        sa.Column("session_id", sa.String(100), primary_key=True),
        sa.Column("agent_id", sa.String(100), primary_key=True, server_default=""),
        sa.Column("project", sa.String(200), nullable=False, server_default="unknown"),
        sa.Column("kind", sa.String(20), nullable=False, server_default="other"),
        sa.Column("job", sa.String(200), nullable=True),
        sa.Column("title", sa.String(300), nullable=True),
        sa.Column("first_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("usage_sessions")
    op.drop_index("ix_usage_calls_agent", table_name="usage_calls")
    op.drop_index("ix_usage_calls_session_occurred", table_name="usage_calls")
    op.drop_index("ix_usage_calls_occurred_at", table_name="usage_calls")
    op.drop_table("usage_calls")
