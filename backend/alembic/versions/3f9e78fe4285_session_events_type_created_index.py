"""Index session events by type and time.

Revision ID: 3f9e78fe4285
Revises: e7b3d9f1a5c2

Readers that count one event type over a recent window (st pulse commits and
done calls, tool and cost rollups) filtered ix_session_events_type and then
read every row of that type since September: st pulse spent ~3.4 s reading
~1M tool_use/tool_result rows to keep the ~230k from the last 7 days.
(event_type, created_at) serves those windows, and equality on event_type as
well, so it replaces ix_session_events_type.

Built CONCURRENTLY outside the migration transaction so live session ingest is
not blocked; IF NOT EXISTS makes a rerun after an interrupted build safe.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "3f9e78fe4285"
down_revision: str | Sequence[str] | None = "e7b3d9f1a5c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAME = "ix_session_events_type_created"


def _drop_if_invalid(name: str) -> None:
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


def upgrade() -> None:
    with op.get_context().autocommit_block():
        _drop_if_invalid(_NAME)
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_NAME} "
            "ON public.session_events (event_type, created_at)"
        )
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS public.ix_session_events_type")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        _drop_if_invalid("ix_session_events_type")
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_session_events_type "
            "ON public.session_events (event_type)"
        )
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS public.{_NAME}")
