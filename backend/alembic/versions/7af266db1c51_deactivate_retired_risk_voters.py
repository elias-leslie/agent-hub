"""deactivate_retired_risk_voters

Revision ID: 7af266db1c51
Revises: 8f56b94092a9
Create Date: 2026-05-18

Following the L3 redesign (commit 30690fc0 in portfolio-ai), the risk
stage runs a single consolidated voter (``risk-neutral-v1``). The two
former voters — ``risk-aggressive-v1`` and ``risk-conservative-v1`` —
are no longer invoked by ``stages.RISK_SLUGS``. They are kept in the DB
(prompt history is part of the audit trail) but flipped to ``is_active=
false`` so:

- the admin UI doesn't list them as available agents
- accidental re-routing through generic agent-picker logic is prevented
- a future experiment that wants the multi-voter shape back can flip
  them back to ``is_active=true`` with one line

Idempotent: only flips rows currently active. Downgrade restores them
to active.
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "7af266db1c51"
down_revision: str | Sequence[str] | None = "8f56b94092a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_RETIRED_SLUGS = ("risk-aggressive-v1", "risk-conservative-v1")


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        text(
            "UPDATE agents SET is_active = false "
            "WHERE slug = ANY(:slugs) AND is_active = true"
        ),
        {"slugs": list(_RETIRED_SLUGS)},
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        text(
            "UPDATE agents SET is_active = true "
            "WHERE slug = ANY(:slugs) AND is_active = false"
        ),
        {"slugs": list(_RETIRED_SLUGS)},
    )
