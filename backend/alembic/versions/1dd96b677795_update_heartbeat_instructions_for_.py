"""update heartbeat instructions for feedback triage

Revision ID: 1dd96b677795
Revises: 67f5caf9bb1f
Create Date: 2026-03-04 09:32:27.692801

Replace soft `st feedback list` bash instruction in Phase 2 with mandatory
`manage_feedback` tool calls. Add concrete checklist and quota (resolve/vote
on 2+ items per heartbeat when open items exist).
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "1dd96b677795"
down_revision: str | Sequence[str] | None = "67f5caf9bb1f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Only the Phase 2 section changes. The old line:
#   "st feedback list → resolve trivial items, create tasks for larger ones."
# becomes a concrete, mandatory checklist.

_OLD_PHASE2 = """\
### 2. Task Health & Feedback
- `manage_tasks(action="list_ready")` for cross-project overview.
- Unblock any blocked/failed/stale tasks.
- st feedback list → resolve trivial items, create tasks for larger ones.
- Triage review wake events: validate findings, skip false positives, create tasks for real issues."""

_NEW_PHASE2 = """\
### 2. Task Health & Feedback (REQUIRED)
- `manage_tasks(action="list_ready")` for cross-project overview.
- Unblock any blocked/failed/stale tasks.
- **Feedback triage** — if `<feedback_summary>` shows open items, you MUST act on at least 2:
  1. `manage_feedback(action="search")` to see the full list with context.
  2. Items you know are fixed → `manage_feedback(action="resolve", item_id="...")`.
  3. Items you've also observed → `manage_feedback(action="vote", item_id="...", comment="...")`.
  4. High-vote friction/improvement items needing code → create a task via `manage_tasks`.
  5. Stale items (>7 days, no longer relevant) → resolve with resolution_note.
- Triage review wake events: validate findings, skip false positives, create tasks for real issues."""


def upgrade() -> None:
    """Replace soft feedback bash instruction with mandatory manage_feedback tool calls."""
    conn = op.get_bind()
    conn.execute(
        text(
            "UPDATE persona "
            "SET heartbeat_instructions_previous = heartbeat_instructions, "
            "    heartbeat_instructions = REPLACE(heartbeat_instructions, :old_text, :new_text), "
            "    version = version + 1, "
            "    updated_at = now() "
            "WHERE heartbeat_instructions IS NOT NULL "
            "  AND heartbeat_instructions LIKE '%st feedback list%'"
        ),
        {"old_text": _OLD_PHASE2, "new_text": _NEW_PHASE2},
    )


def downgrade() -> None:
    """Restore previous heartbeat instructions from backup column."""
    conn = op.get_bind()
    conn.execute(
        text(
            "UPDATE persona "
            "SET heartbeat_instructions = heartbeat_instructions_previous, "
            "    heartbeat_instructions_previous = NULL, "
            "    version = version + 1, "
            "    updated_at = now() "
            "WHERE heartbeat_instructions_previous IS NOT NULL"
        )
    )
