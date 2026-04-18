"""strengthen heartbeat finalize gate

Revision ID: d3931b3024b3
Revises: d1f2ec627e4b
Create Date: 2026-03-08 23:27:16.653808

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d3931b3024b3"
down_revision: str | Sequence[str] | None = "d1f2ec627e4b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HEARTBEAT_PROMPT = "persona-heartbeat-orchestrator"
OLD_TEXT = (
    '- If you need a current cleanup read on one project, use `manage_tasks(action="cleanup_status", project_id="...")` instead of ad hoc shell inspection.\n'
    '- If cleanup debt is present and the project has no more urgent live execution problem, use `manage_tasks(action="cleanup_checkpoints", project_id="...")` to clear safe checkpoint cleanup cases before dispatching additional low-confidence maintenance work.\n'
    '- If cleanup output shows `NEEDS_MERGE` or `CONFLICT` for a completed, failed, blocked, or conflicted task residue, use `manage_tasks(action="finalize_merge", task_id="...", project_id="...")` to finish the canonical merge/cleanup path before dispatching more work.\n'
    '- Do not treat a task as fully closed just because it says `completed` if cleanup still shows `NEEDS_MERGE` or `CONFLICT`; finalize it or reconcile why it cannot merge.\n'
)
NEW_TEXT = (
    '- If you need a current cleanup read on one project, use `manage_tasks(action="cleanup_status", project_id="...")` instead of ad hoc shell inspection.\n'
    '- Treat `cleanup_status` as the short decision surface. If it includes `finalize:` or `conflicts:` candidates for the target project, resolve those before dispatching more low-confidence refactor/maintenance work in that same project.\n'
    '- If cleanup debt is present and the project has no more urgent live execution problem, use `manage_tasks(action="cleanup_checkpoints", project_id="...")` to clear safe checkpoint cleanup cases before dispatching additional low-confidence maintenance work.\n'
    '- If cleanup output shows `NEEDS_MERGE` or `CONFLICT` for a completed, failed, blocked, or conflicted task residue, use `manage_tasks(action="finalize_merge", task_id="...", project_id="...")` to finish the canonical merge/cleanup path before dispatching more work.\n'
    '- Do not treat a task as fully closed just because it says `completed` if cleanup still shows `NEEDS_MERGE` or `CONFLICT`; finalize it or reconcile why it cannot merge.\n'
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
