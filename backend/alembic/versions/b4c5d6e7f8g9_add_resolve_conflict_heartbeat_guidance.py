"""add resolve_conflict heartbeat guidance

Revision ID: b4c5d6e7f8g9
Revises: a3f20b69e97e
Create Date: 2026-03-09 01:45:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4c5d6e7f8g9"
down_revision: str | Sequence[str] | None = "a3f20b69e97e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HEARTBEAT_PROMPT = "persona-heartbeat-orchestrator"
OLD_TEXT = (
    '- Treat `cleanup_status` as the short decision surface. Map it literally: `finalize:` means use `manage_tasks(action="finalize_merge", ...)`; `conflicts:` means finish merge resolution before dispatching more work, starting with `finalize_merge` for completed/blocked residue; `review:` means do NOT use `finalize_merge` blindly and do NOT dispatch more low-confidence work until you inspect or reconcile the residue.\n'
)
NEW_TEXT = (
    '- Treat `cleanup_status` as the short decision surface. Map it literally: `finalize:` means use `manage_tasks(action="finalize_merge", ...)`; `conflicts:` means use `manage_tasks(action="resolve_conflict", ...)` to reopen and dispatch conflict-resolution work on that exact task before any new low-confidence work; `review:` means do NOT use `finalize_merge` blindly and do NOT dispatch more low-confidence work until you inspect or reconcile the residue.\n'
)


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE prompts
            SET content = REPLACE(content, :old_text, :new_text),
                updated_at = NOW()
            WHERE slug = :slug
            """
        ),
        {
            "slug": HEARTBEAT_PROMPT,
            "old_text": OLD_TEXT,
            "new_text": NEW_TEXT,
        },
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE prompts
            SET content = REPLACE(content, :new_text, :old_text),
                updated_at = NOW()
            WHERE slug = :slug
            """
        ),
        {
            "slug": HEARTBEAT_PROMPT,
            "old_text": OLD_TEXT,
            "new_text": NEW_TEXT,
        },
    )
