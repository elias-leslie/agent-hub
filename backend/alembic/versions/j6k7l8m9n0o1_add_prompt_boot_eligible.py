"""add_prompt_boot_eligible

Revision ID: j6k7l8m9n0o1
Revises: i5j6k7l8m9n0
Create Date: 2026-05-10 00:00:00.000000

Adds prompts.boot_eligible — when true, the prompt is auto-injected into
runtime-context boot blocks (without requiring a per-profile pin override).
Mirrors the column on prompt_revisions so the audit log captures it.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "j6k7l8m9n0o1"
down_revision: str | Sequence[str] | None = "i5j6k7l8m9n0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "prompts",
        sa.Column(
            "boot_eligible",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "prompt_revisions",
        sa.Column(
            "boot_eligible",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )

    # Backfill: any prompt currently pinned via runtime_context_overrides at the
    # global (project_id IS NULL) layer with mode='include' should become
    # boot_eligible by default — that's exactly what those overrides express
    # today, so this preserves behavior under the new model.
    op.execute(
        """
        UPDATE prompts
        SET boot_eligible = true
        WHERE slug IN (
            SELECT DISTINCT source_id
            FROM runtime_context_overrides
            WHERE source_type = 'prompt'
              AND mode = 'include'
              AND enabled = true
              AND project_id IS NULL
        )
        """
    )


def downgrade() -> None:
    op.drop_column("prompt_revisions", "boot_eligible")
    op.drop_column("prompts", "boot_eligible")
