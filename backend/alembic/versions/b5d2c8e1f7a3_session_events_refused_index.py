"""Index the provider refusals in session events.

Revision ID: b5d2c8e1f7a3
Revises: d3b8f1a6c294

``st models route`` (launch-defaults with facts) lists the newest provider refusals: events whose
usage->provider_outcome->kind is 'refused'. With no index that read all 2.9M session_events rows
(~800 ms); the 71 refusals are served by a partial index on created_at.

Built CONCURRENTLY outside the migration transaction so live session ingest is not blocked;
IF NOT EXISTS makes a rerun after an interrupted build safe.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "b5d2c8e1f7a3"
down_revision: str | Sequence[str] | None = "d3b8f1a6c294"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAME = "ix_session_events_refused_created"


def _drop_if_invalid(name: str) -> None:
    # An interrupted concurrent build leaves an INVALID index that IF NOT EXISTS would keep.
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
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_NAME} ON public.session_events (created_at DESC) "
            "WHERE ((usage -> 'provider_outcome') ->> 'kind') = 'refused'"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS public.{_NAME}")
