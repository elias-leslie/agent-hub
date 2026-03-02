"""backfill tool_result content from tool_output

Revision ID: 163e34a7c829
Revises: 4181a970370b
Create Date: 2026-03-02 10:07:15.185296

All tool_result events created before commit e7c6459 have content = NULL
because the content extraction was added in that commit.  This migration
back-fills the content column from the tool_output JSONB using the same
key priority as _extract_tool_result_content: result, content, output,
message.  Values are capped at 2000 characters via LEFT().
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "163e34a7c829"
down_revision: str | Sequence[str] | None = "4181a970370b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Back-fill content from tool_output JSONB for historical tool_result events.
    # Key priority matches _extract_tool_result_content: result, content, output, message.
    # COALESCE tries each key in order; LEFT() caps at 2000 chars.
    # NULLIF guards against empty strings so we don't overwrite NULL with ''.
    op.execute(
        """
        UPDATE session_events
        SET content = LEFT(
            COALESCE(
                NULLIF(tool_output->>'result',  ''),
                NULLIF(tool_output->>'content', ''),
                NULLIF(tool_output->>'output',  ''),
                NULLIF(tool_output->>'message', '')
            ),
            2000
        )
        WHERE event_type = 'tool_result'
          AND content IS NULL
          AND tool_output IS NOT NULL
        """
    )


def downgrade() -> None:
    # Revert: set content back to NULL for rows we back-filled.
    # We cannot perfectly distinguish "was NULL before" vs "was set by app",
    # but all rows that had content set by the app were created *after* the
    # extraction logic was deployed, so they would not have been touched by
    # the upgrade (they already had content != NULL).  Safe to NULL them all
    # for tool_result rows -- the app will re-populate on next write.
    op.execute(
        """
        UPDATE session_events
        SET content = NULL
        WHERE event_type = 'tool_result'
        """
    )
