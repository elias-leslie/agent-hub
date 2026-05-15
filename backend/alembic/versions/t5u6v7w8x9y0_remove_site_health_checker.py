"""Remove site health checker workflow surfaces.

Revision ID: t5u6v7w8x9y0
Revises: s5t6u7v8w9x0
Create Date: 2026-05-15 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "t5u6v7w8x9y0"
down_revision: str | Sequence[str] | None = "s5t6u7v8w9x0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DELETE FROM workflow_schedule_controls WHERE schedule_id = 'site_health_check'")
    op.execute(
        """
        UPDATE prompts
        SET content = replace(
            content,
            'designer/ux-polisher, site-checker, git-agent, verifier.',
            'designer/ux-polisher, git-agent, verifier.'
        )
        WHERE slug = 'persona-agent-routing-catalog'
        """
    )
    op.execute(
        """
        UPDATE sessions
        SET status = 'completed',
            health_detail = 'completed',
            summary_oneliner = COALESCE(NULLIF(summary_oneliner, ''), 'Site checker removed.'),
            updated_at = NOW()
        WHERE agent_slug = 'site-checker'
          AND status = 'active'
        """
    )
    op.execute("DELETE FROM agents WHERE slug = 'site-checker'")


def downgrade() -> None:
    op.execute(
        """
        UPDATE prompts
        SET content = replace(
            content,
            'designer/ux-polisher, git-agent, verifier.',
            'designer/ux-polisher, site-checker, git-agent, verifier.'
        )
        WHERE slug = 'persona-agent-routing-catalog'
        """
    )
