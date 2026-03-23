"""dedupe narration tags

Revision ID: 46da0d007484
Revises: bcb0ec5298bb
Create Date: 2026-03-23 19:29:35.283508

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "46da0d007484"
down_revision: str | Sequence[str] | None = "bcb0ec5298bb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UNIQUE_CONSTRAINT = "uq_narration_tags_task_session_type_content"


def upgrade() -> None:
    """Remove duplicate narration rows and enforce idempotent storage."""
    op.execute(
        sa.text(
            """
            DELETE FROM task_narration_tags
            WHERE id IN (
                SELECT id
                FROM (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY task_id, session_id, tag_type, content
                               ORDER BY id
                           ) AS row_number
                    FROM task_narration_tags
                ) duplicate_rows
                WHERE duplicate_rows.row_number > 1
            )
            """
        )
    )
    op.create_unique_constraint(
        _UNIQUE_CONSTRAINT,
        "task_narration_tags",
        ["task_id", "session_id", "tag_type", "content"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(_UNIQUE_CONSTRAINT, "task_narration_tags", type_="unique")
