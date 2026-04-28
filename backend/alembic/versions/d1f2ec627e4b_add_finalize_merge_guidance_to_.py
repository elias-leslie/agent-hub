"""add terminal-residue guidance to heartbeat prompt

Revision ID: d1f2ec627e4b
Revises: 0787049c485f
Create Date: 2026-03-08 23:17:39.056422

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd1f2ec627e4b'
down_revision: str | Sequence[str] | None = '0787049c485f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HEARTBEAT_PROMPT = "persona-heartbeat-orchestrator"
OLD_TEXT = (
    "- If cleanup debt is present and the project has no more urgent live execution problem, "
    "use `manage_tasks(action=\"cleanup_checkpoints\", project_id=\"...\")` to clear safe checkpoint "
    "cleanup cases before dispatching additional low-confidence maintenance work.\n"
    "- Safe cleanup means merged/retired residue only. If cleanup output shows dirty, conflicting, "
    "or review-needed checkpoints, stop there and reconcile the underlying task/workstream instead "
    "of forcing deletion.\n"
)
NEW_TEXT = (
    "- If cleanup debt is present and the project has no more urgent live execution problem, "
    "use `manage_tasks(action=\"cleanup_checkpoints\", project_id=\"...\")` to clear safe checkpoint "
    "cleanup cases before dispatching additional low-confidence maintenance work.\n"
    "- If cleanup output shows terminal task residue (`finalize:`, `NEEDS_MERGE`, or `CONFLICT`) "
    "for a completed, failed, blocked, or conflicted task, use `manage_tasks(action=\"reconcile\", "
    "task_id=\"...\", project_id=\"...\")` to reopen or clear the exact residue before dispatching "
    "more work.\n"
    "- Do not treat a task as fully closed just because it says `completed` if cleanup still shows "
    "`finalize:`, `NEEDS_MERGE`, or `CONFLICT`; reconcile it or clear safe checkpoints.\n"
    "- Safe cleanup means merged/retired residue only. If cleanup output shows dirty, conflicting, "
    "or review-needed checkpoints, stop there and reconcile the underlying task/workstream instead "
    "of forcing deletion.\n"
)


def upgrade() -> None:
    """Update heartbeat prompt with explicit residue cleanup guidance."""
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
    """Restore the previous heartbeat guidance."""
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
