"""index_hygiene_session_fk_indexes

Revision ID: a2d4f6b8c0e1
Revises: 9cff0500948a
Create Date: 2026-06-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a2d4f6b8c0e1"
down_revision: str | Sequence[str] | None = "9cff0500948a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_session_events_session_turn", table_name="session_events")
    op.drop_index("ix_sessions_parent_session_id", table_name="sessions")
    op.create_index(
        "ix_memory_injection_metrics_session_id",
        "memory_injection_metrics",
        ["session_id"],
    )
    op.create_index("ix_truncation_events_session_id", "truncation_events", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_truncation_events_session_id", table_name="truncation_events")
    op.drop_index("ix_memory_injection_metrics_session_id", table_name="memory_injection_metrics")
    op.create_index("ix_sessions_parent_session_id", "sessions", ["parent_session_id"])
    op.create_index(
        "ix_session_events_session_turn",
        "session_events",
        ["session_id", "turn", "sequence"],
    )
