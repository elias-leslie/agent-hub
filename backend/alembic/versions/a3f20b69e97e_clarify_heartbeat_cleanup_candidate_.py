"""clarify heartbeat cleanup candidate handling

Revision ID: a3f20b69e97e
Revises: d3931b3024b3
Create Date: 2026-03-08 23:54:31.046898

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3f20b69e97e"
down_revision: str | Sequence[str] | None = "d3931b3024b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HEARTBEAT_PROMPT = "persona-heartbeat-orchestrator"
OLD_TEXT = (
    '- If you need a current cleanup read on one project, use `manage_tasks(action="cleanup_status", project_id="...")` instead of ad hoc shell inspection.\n'
    '- Treat `cleanup_status` as the short decision surface. If it includes `finalize:` or `conflicts:` candidates for the target project, resolve those before dispatching more low-confidence refactor/maintenance work in that same project.\n'
    '- If cleanup debt is present and the project has no more urgent live execution problem, use `manage_tasks(action="cleanup_checkpoints", project_id="...")` to clear safe checkpoint cleanup cases before dispatching additional low-confidence maintenance work.\n'
    '- If cleanup output shows terminal task residue (`finalize:`, `NEEDS_MERGE`, or `CONFLICT`) for a completed, failed, blocked, or conflicted task, use `manage_tasks(action="reconcile", task_id="...", project_id="...")` to reopen or clear the exact residue before dispatching more work.\n'
    '- Do not treat a task as fully closed just because it says `completed` if cleanup still shows `finalize:`, `NEEDS_MERGE`, or `CONFLICT`; reconcile it or clear safe checkpoints.\n'
)
NEW_TEXT = (
    '- If you need a current cleanup read on one project, use `manage_tasks(action="cleanup_status", project_id="...")` instead of ad hoc shell inspection.\n'
    '- Treat `cleanup_status` as the short decision surface. Map it literally: `finalize:` means use `manage_tasks(action="reconcile", ...)`; `conflicts:` means resolve active conflicts before dispatching more work, starting with `resolve_conflict` for active conflict residue or `reconcile` for terminal completed/blocked residue; `review:` means inspect or reconcile the residue before more low-confidence work.\n'
    '- If cleanup debt is present and the project has no more urgent live execution problem, use `manage_tasks(action="cleanup_checkpoints", project_id="...")` to clear safe checkpoint cleanup cases before dispatching additional low-confidence maintenance work.\n'
    '- Do not use `cleanup_checkpoints` for a cleanup candidate that is only surfaced under `review:`. Review candidates usually mean missing-task residue, dirty checkpoints, or ambiguous state; inspect with `get_context`, `query_sessions`, `cleanup_checkpoints`, or `reconcile` first.\n'
    '- Do not treat a task as fully closed just because it says `completed` if cleanup still shows `finalize:` or `conflicts:` residue; finish the canonical merge/cleanup path or reconcile why it cannot merge before dispatching more work.\n'
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
