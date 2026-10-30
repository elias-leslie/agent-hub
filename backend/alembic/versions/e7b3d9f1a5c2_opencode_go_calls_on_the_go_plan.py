"""OpenCode Go calls made under the Go plan bill as subscription, not metered

Revision ID: e7b3d9f1a5c2
Revises: c4f7a1e9d2b6
Create Date: 2026-10-29 23:50:00.000000

OpenCode Go calls logged before it was listed as a flat subscription provider were priced per token
as metered cash. The owner's $40/month Go plan covers them, so rows from the plan's start move to
subscription: $0 marginal cash, their list price kept as api_equiv_usd (the metered price was the
catalog list price for the same tokens). Without an opencode-go plan row nothing changes.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e7b3d9f1a5c2"
down_revision: str | Sequence[str] | None = "c4f7a1e9d2b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE cost_logs l SET billing_mode = 'subscription', api_equiv_usd = l.cost_usd, cost_usd = 0 "
            "FROM subscription_plans p "
            "WHERE p.provider = 'opencode-go' AND l.created_at >= p.effective_from "
            "AND (p.effective_to IS NULL OR l.created_at < p.effective_to) "
            "AND l.billing_mode = 'metered' AND l.model LIKE 'opencode-go/%' AND l.api_equiv_usd IS NULL"
        )
    )


def downgrade() -> None:
    """The plan covered these calls; they were never metered cash."""
