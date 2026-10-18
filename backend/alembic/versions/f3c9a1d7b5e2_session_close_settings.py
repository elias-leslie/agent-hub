"""add session_close_settings

Revision ID: f3c9a1d7b5e2
Revises: e6b1c8d4a2f9
Create Date: 2026-10-17 22:30:00.000000

When Agent Hub closes a session is data, not code: one settings row (id=1) holds the
reaper and live-classification close thresholds and the Codex transcript collector's
scan window and inactive-close switch. Defaults equal the values that were hardcoded.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f3c9a1d7b5e2"
down_revision: str | Sequence[str] | None = "e6b1c8d4a2f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "session_close_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dead_candidate_after_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("reapable_after_minutes", sa.Integer(), nullable=False, server_default="360"),
        sa.Column("zero_event_close_after_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("transcript_sync_close_after_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("completion_close_after_minutes", sa.Integer(), nullable=False, server_default="240"),
        sa.Column("any_session_close_after_minutes", sa.Integer(), nullable=False, server_default="1440"),
        sa.Column("codex_close_inactive_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("codex_scan_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("updated_by", sa.String(160), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_session_close_settings_singleton"),
    )
    op.execute("INSERT INTO session_close_settings (id) VALUES (1)")


def downgrade() -> None:
    op.drop_table("session_close_settings")
