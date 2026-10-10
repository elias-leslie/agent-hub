"""Retire Telegram data: session_bindings Telegram columns and bot credentials.

Revision ID: a7c3e9f1b2d4
Revises: f3a4b5c6d7e8

Stage 6 of docs/audits/2026-10-value-audit-plan.md (owner retired Telegram on
2026-10-10). Drops session_bindings.telegram_chat_id/thread_id/message_id and
their two indexes (every row was NULL) and deletes the encrypted
_system_telegram_bot credential rows. Upgrade is idempotent.

Downgrade re-adds the nullable columns and indexes. The deleted credentials are
not restorable by design: they are retired secrets and are never stored in git.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "a7c3e9f1b2d4"
down_revision: str | Sequence[str] | None = "f3a4b5c6d7e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = ("telegram_chat_id", "telegram_thread_id", "telegram_message_id")


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS public.ix_session_bindings_telegram")
    op.execute("DROP INDEX IF EXISTS public.ix_session_bindings_telegram_chat_id")
    for column in _COLUMNS:
        op.execute(f"ALTER TABLE public.session_bindings DROP COLUMN IF EXISTS {column}")
    op.execute("DELETE FROM public.credentials WHERE provider = '_system_telegram_bot'")


def downgrade() -> None:
    for column in _COLUMNS:
        op.execute(
            f"ALTER TABLE public.session_bindings ADD COLUMN IF NOT EXISTS {column} character varying(100)"
        )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_session_bindings_telegram "
        "ON public.session_bindings USING btree (telegram_chat_id, telegram_thread_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_session_bindings_telegram_chat_id "
        "ON public.session_bindings USING btree (telegram_chat_id)"
    )
