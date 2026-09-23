"""Add native transcript event identity, timestamp, and usage evidence.

Revision ID: 7e4a6c8d0f21
Revises: 6d7e8f9a0b1c
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7e4a6c8d0f21"
down_revision: str | None = "6d7e8f9a0b1c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("session_events", sa.Column("source_event_id", sa.String(255), nullable=True))
    op.add_column("session_events", sa.Column("call_id", sa.String(255), nullable=True))
    op.add_column("session_events", sa.Column("source_timestamp", sa.DateTime(timezone=True), nullable=True))
    op.add_column("session_events", sa.Column("usage", sa.JSON(), nullable=True))
    op.create_index(
        "uq_session_events_source_event",
        "session_events",
        ["session_id", "source_event_id"],
        unique=True,
        postgresql_where=sa.text("source_event_id IS NOT NULL"),
    )
    op.create_index("ix_session_events_call_id", "session_events", ["session_id", "call_id"])


def downgrade() -> None:
    op.drop_index("ix_session_events_call_id", table_name="session_events")
    op.drop_index("uq_session_events_source_event", table_name="session_events")
    op.drop_column("session_events", "usage")
    op.drop_column("session_events", "source_timestamp")
    op.drop_column("session_events", "source_event_id")
    op.drop_column("session_events", "call_id")
