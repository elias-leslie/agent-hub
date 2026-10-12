"""Drop tables and client columns retired by the value audit (Stage 4).

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7

Stage 4 of the October 2026 value audit. Pulse, webhooks, web push,
client kill-switch controls, persona scheduled jobs and action requests lost
their last readers in Stages 2-3. Their rows were archived with pg_dump and
test-restored before this ran (backups/2026-10-cleanup/MANIFEST.json); data is
restored from that archive, not by this migration.

Upgrade is idempotent (IF EXISTS). Downgrade recreates the exact pre-drop
schema from the sibling .sql file (taken from the archived schema dump) and
re-adds clients.rate_limit_rpm/rate_limit_tpm with their former defaults.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "f3a4b5c6d7e8"
down_revision: str | Sequence[str] | None = "e2f3a4b5c6d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA_PATH = Path(__file__).with_suffix(".sql")
# Children before parents (pulse_items references pulse_briefs).
_TABLES = (
    "pulse_items",
    "pulse_feedback_events",
    "pulse_improvement_proposals",
    "pulse_source_observations",
    "pulse_briefs",
    "webhook_subscriptions",
    "client_controls",
    "push_subscriptions",
    "persona_scheduled_jobs",
    "action_requests",
)


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"DROP TABLE IF EXISTS public.{table}")
    op.execute("ALTER TABLE public.clients DROP COLUMN IF EXISTS rate_limit_rpm")
    op.execute("ALTER TABLE public.clients DROP COLUMN IF EXISTS rate_limit_tpm")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE public.clients "
        "ADD COLUMN IF NOT EXISTS rate_limit_rpm integer NOT NULL DEFAULT 60, "
        "ADD COLUMN IF NOT EXISTS rate_limit_tpm integer NOT NULL DEFAULT 100000"
    )
    for statement in _SCHEMA_PATH.read_text().split(";\n"):
        if statement.strip():
            op.execute(statement)
