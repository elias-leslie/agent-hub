"""Compressed per-session archives of old finished sessions' events.

Revision ID: c4e8a1f3d5b7
Revises: b7d2e4f6a8c0

Finished sessions idle past settings.session_events_archive_after_days keep
their events as one xz-compressed JSONL payload instead of raw rows. The
payload is already compressed, so its storage is EXTERNAL (no second pglz pass).
Downgrade puts archived events back into session_events before dropping it.
"""

import json
import lzma
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c4e8a1f3d5b7"
down_revision: str | Sequence[str] | None = "b7d2e4f6a8c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "session_event_archives",
        sa.Column("session_id", sa.String(36), sa.ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("format", sa.String(32), nullable=False),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("raw_bytes", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("summary", postgresql.JSONB(), nullable=False),
        sa.Column("first_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.execute("ALTER TABLE session_event_archives ALTER COLUMN payload SET STORAGE EXTERNAL")


def downgrade() -> None:
    bind = op.get_bind()
    table_columns = {row[0] for row in bind.execute(sa.text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = 'session_events'"
    ))}
    session_ids = bind.execute(sa.text("SELECT session_id FROM session_event_archives ORDER BY session_id")).scalars().all()
    for session_id in session_ids:  # one payload in memory at a time
        fmt, payload = bind.execute(
            sa.text("SELECT format, payload FROM session_event_archives WHERE session_id = :sid"), {"sid": session_id}
        ).one()
        if fmt != "jsonl+xz":
            raise RuntimeError(f"Unknown session event archive format {fmt!r} for {session_id}")
        lines = [line for line in lzma.decompress(payload).decode().split("\n") if line]
        if not lines:
            continue
        cols = ", ".join(f'"{name}"' for name in json.loads(lines[0]) if name in table_columns)
        inserted = bind.execute(
            sa.text(
                f"INSERT INTO session_events ({cols}) SELECT {cols} "
                "FROM json_populate_recordset(NULL::session_events, CAST(:rows AS json)) ON CONFLICT DO NOTHING"
            ),
            {"rows": "[" + ",".join(lines) + "]"},
        ).rowcount
        if inserted != len(lines):
            raise RuntimeError(
                f"Session {session_id}: only {inserted} of {len(lines)} archived events fit back into session_events"
            )
    op.drop_table("session_event_archives")
