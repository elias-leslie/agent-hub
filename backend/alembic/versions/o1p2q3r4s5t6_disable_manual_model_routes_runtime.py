"""disable_manual_model_routes_runtime

Revision ID: o1p2q3r4s5t6
Revises: n0o1p2q3r4s5
Create Date: 2026-05-13 08:35:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "o1p2q3r4s5t6"
down_revision = "n0o1p2q3r4s5"
branch_labels = None
depends_on = None


DISABLE_REASON = (
    "Disabled 2026-05-13: manual_model_routes are not an execution source; "
    "update agents.primary_model_id/fallback_models via agent slug routing."
)


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE manual_model_routes
            SET enabled = false,
                reason = CASE
                    WHEN reason IS NULL OR btrim(reason) = '' THEN :reason
                    WHEN position(:reason in reason) > 0 THEN reason
                    ELSE reason || E'\n' || :reason
                END,
                updated_at = now()
            WHERE enabled = true
            """
        ).bindparams(reason=DISABLE_REASON)
    )


def downgrade() -> None:
    # Do not re-enable manual routes. They may have been disabled intentionally.
    pass
