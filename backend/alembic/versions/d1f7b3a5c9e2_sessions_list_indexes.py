"""Indexes for the sessions list redesign.

Revision ID: d1f7b3a5c9e2
Revises: c9e5a1b3d7f2

The list orders by last activity (coalesce(last_activity_at, created_at) DESC,
id DESC) with keyset paging, globally or within one project; event counts,
by-type summaries, titles and the usage rollup group or filter events by type
within one session. A session_type-leading index was rejected: kind=coding,chat
is an IN over three types, which cannot return rows in that order.

Built CONCURRENTLY outside the migration transaction so live session ingest is
not blocked; IF NOT EXISTS makes a rerun after an interrupted build safe.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "d1f7b3a5c9e2"
down_revision: str | Sequence[str] | None = "c9e5a1b3d7f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEXES = (
    (
        "ix_sessions_last_active",
        "public.sessions ((coalesce(last_activity_at, created_at)) DESC, id DESC)",
    ),
    (
        "ix_sessions_project_last_active",
        "public.sessions (project_id, (coalesce(last_activity_at, created_at)) DESC, id DESC)",
    ),
    (
        "ix_session_events_session_type",
        "public.session_events (session_id, event_type)",
    ),
)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for name, target in _INDEXES:
            # An interrupted concurrent build leaves an INVALID index that
            # IF NOT EXISTS would keep; drop it so the rebuild is real.
            op.execute(
                f"""
                DO $$
                BEGIN
                  IF EXISTS (
                    SELECT 1 FROM pg_index i
                    JOIN pg_class c ON c.oid = i.indexrelid
                    WHERE c.relname = '{name}' AND NOT i.indisvalid
                  ) THEN
                    EXECUTE 'DROP INDEX public.{name}';
                  END IF;
                END $$
                """
            )
            op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON {target}")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name, _ in reversed(_INDEXES):
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS public.{name}")
