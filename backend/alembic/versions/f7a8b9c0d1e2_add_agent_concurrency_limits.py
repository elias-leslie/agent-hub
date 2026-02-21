"""add_agent_concurrency_and_quota_limits

Revision ID: f7a8b9c0d1e2
Revises: 031faf39e26f
Create Date: 2026-02-21 12:00:00.000000

Adds concurrency and quota columns to agents table:
- max_concurrency, max_subagent_concurrency (parallel execution limits)
- daily_token_budget, hourly_request_limit (execution quotas)
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f7a8b9c0d1e2"
down_revision: str | Sequence[str] | None = "031faf39e26f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("max_concurrency", sa.Integer(), nullable=True))
    op.add_column("agents", sa.Column("max_subagent_concurrency", sa.Integer(), nullable=True))
    op.add_column("agents", sa.Column("daily_token_budget", sa.Integer(), nullable=True))
    op.add_column("agents", sa.Column("hourly_request_limit", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("agents", "hourly_request_limit")
    op.drop_column("agents", "daily_token_budget")
    op.drop_column("agents", "max_subagent_concurrency")
    op.drop_column("agents", "max_concurrency")
