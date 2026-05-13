"""disable_stale_portfolio_grok_routes

Revision ID: n0o1p2q3r4s5
Revises: m9n0o1p2q3r4
Create Date: 2026-05-13 08:25:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "n0o1p2q3r4s5"
down_revision: str | Sequence[str] | None = "m9n0o1p2q3r4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PORTFOLIO_COMMITTEE_AGENT_SLUGS = (
    "bear-researcher-v1",
    "bull-researcher-v1",
    "fundamentals-v1",
    "news-grounded-v1",
    "portfolio-mgr-v1",
    "risk-aggressive-v1",
    "risk-conservative-v1",
    "risk-neutral-v1",
    "sentiment-grounded-v1",
    "technical-v1",
    "trader-v1",
)

STALE_ROUTE_REASON = (
    "Route TradingAgents committee through working providers after Claude "
    "credential smoke returned 401 during TSLA validation."
)
DISABLED_MARKER = (
    "\nDisabled 2026-05-13: stale portfolio-ai Grok override; "
    "follow agents.primary_model_id via agent_slug routing."
)


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.execute(
        sa.text(
            f"""
            UPDATE manual_model_routes
            SET
                enabled = false,
                reason = COALESCE(reason, '') || :disabled_marker,
                updated_at = NOW()
            WHERE enabled = true
              AND workload_profile IS NULL
              AND owner = 'codex'
              AND primary_model_id = 'xai/grok-4.3'
              AND reason = :stale_route_reason
              AND agent_slug IN ({_quoted(PORTFOLIO_COMMITTEE_AGENT_SLUGS)})
            """
        ).bindparams(
            disabled_marker=DISABLED_MARKER,
            stale_route_reason=STALE_ROUTE_REASON,
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            f"""
            UPDATE manual_model_routes
            SET
                enabled = true,
                reason = REPLACE(reason, :disabled_marker, ''),
                updated_at = NOW()
            WHERE enabled = false
              AND workload_profile IS NULL
              AND owner = 'codex'
              AND primary_model_id = 'xai/grok-4.3'
              AND reason LIKE ('%' || :disabled_marker)
              AND agent_slug IN ({_quoted(PORTFOLIO_COMMITTEE_AGENT_SLUGS)})
            """
        ).bindparams(disabled_marker=DISABLED_MARKER)
    )
