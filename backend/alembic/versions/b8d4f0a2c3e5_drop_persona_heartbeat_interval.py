"""Drop persona.heartbeat_interval_minutes (retired persona heartbeat).

Revision ID: b8d4f0a2c3e5
Revises: a7c3e9f1b2d4

Value-audit follow-up H (task-b3704c2a053f4e97). Persona heartbeat was retired in
audit Stage 3.2; this removes its last column. The persona table was archived first to
backups/2026-10-cleanup/persona-heartbeat.dump (MANIFEST-persona-heartbeat.json,
test-restored). Upgrade is idempotent.

Downgrade re-adds the column with its former default; values restore from the archive.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "b8d4f0a2c3e5"
down_revision: str | Sequence[str] | None = "a7c3e9f1b2d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE public.persona DROP COLUMN IF EXISTS heartbeat_interval_minutes")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE public.persona ADD COLUMN IF NOT EXISTS heartbeat_interval_minutes "
        "integer DEFAULT 60"
    )
