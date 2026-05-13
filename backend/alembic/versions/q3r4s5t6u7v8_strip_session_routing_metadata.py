"""strip_session_routing_metadata

Revision ID: q3r4s5t6u7v8
Revises: p2q3r4s5t6u7
Create Date: 2026-05-13 09:30:00.000000
"""

from __future__ import annotations

from alembic import op

revision = "q3r4s5t6u7v8"
down_revision = "p2q3r4s5t6u7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE sessions
        SET provider_metadata = (provider_metadata::jsonb - 'routing')::json
        WHERE provider_metadata IS NOT NULL
          AND provider_metadata::jsonb ? 'routing'
        """
    )


def downgrade() -> None:
    # Removed routing metadata described a deleted router and cannot be recreated.
    pass
