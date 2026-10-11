"""Recompute stale memory token counts.

Revision ID: f3b9d5e7a1c4
Revises: e2a8c4f6b1d3

Episode content updates left memories.token_count stale until the repository
update path derived it from content. token_count is a derived cache of
app.services.memory.budget.count_tokens (len(content) // 4); this resets only
rows that disagree. Revisions are untouched. Idempotent; downgrade is a no-op.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "f3b9d5e7a1c4"
down_revision: str | Sequence[str] | None = "e2a8c4f6b1d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE memories SET token_count = COALESCE(length(content), 0) / 4 "
        "WHERE token_count IS DISTINCT FROM COALESCE(length(content), 0) / 4"
    )


def downgrade() -> None:
    pass
