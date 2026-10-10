"""Drop context_maintenance_ingest (retired Memory Curator review ledger).

Revision ID: c9e5a1b3d7f2
Revises: b8d4f0a2c3e5

Value-audit leftovers (task-aac01257d7f841c5). The table recorded reviews already
processed by the retired Memory Curator; nothing reads or writes it since f679ea351.
It was archived first to backups/2026-10-cleanup/context_maintenance_ingest.dump
(MANIFEST-context_maintenance_ingest.json, 47 rows, test-restored). Upgrade is idempotent.

Downgrade recreates the empty table; rows restore from the archive.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c9e5a1b3d7f2"
down_revision: str | Sequence[str] | None = "b8d4f0a2c3e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.context_maintenance_ingest")


def downgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS public.context_maintenance_ingest ("
        "record_id varchar(36) NOT NULL, "
        "CONSTRAINT pk_context_maintenance_ingest PRIMARY KEY (record_id))"
    )
