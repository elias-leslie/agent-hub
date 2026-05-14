"""Remove Claude workload credentials and auth preferences.

Revision ID: s5t6u7v8w9x0
Revises: r4s5t6u7v8w9
Create Date: 2026-05-14 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "s5t6u7v8w9x0"
down_revision: str | Sequence[str] | None = "r4s5t6u7v8w9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DELETE FROM credentials WHERE provider IN ('anthropic', 'claude')")
    op.execute("DELETE FROM user_preferences WHERE key = 'claude_auth_preference'")
    op.execute(
        """
        UPDATE models
        SET availability = 'external_reference_only; claude_code_tui_only_not_agent_hub_routable',
            updated_at = NOW()
        WHERE provider = 'claude'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE models
        SET availability = NULL,
            updated_at = NOW()
        WHERE provider = 'claude'
          AND availability = 'external_reference_only; claude_code_tui_only_not_agent_hub_routable'
        """
    )
