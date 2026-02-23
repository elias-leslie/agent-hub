"""option_d_drop_client_secrets_add_budgets

Revision ID: 31f7c68cf57f
Revises: g8h9i0j1k2l3
Create Date: 2026-02-23 14:00:00.000000

Option D schema changes:
1. DROP secret_hash and secret_prefix from clients table
   (Agent Hub binds to localhost; client_id alone suffices for identification)
2. ADD budget columns to project_permissions table
   (daily_cost_budget_usd, monthly_cost_budget_usd, budget_alert_threshold)
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "31f7c68cf57f"
down_revision: str | Sequence[str] | None = "g8h9i0j1k2l3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- clients: drop secret columns ---
    op.drop_column("clients", "secret_hash")
    op.drop_column("clients", "secret_prefix")

    # --- project_permissions: add budget columns ---
    op.add_column(
        "project_permissions",
        sa.Column("daily_cost_budget_usd", sa.Float(), nullable=True),
    )
    op.add_column(
        "project_permissions",
        sa.Column("monthly_cost_budget_usd", sa.Float(), nullable=True),
    )
    op.add_column(
        "project_permissions",
        sa.Column(
            "budget_alert_threshold",
            sa.Float(),
            nullable=False,
            server_default="0.8",
        ),
    )


def downgrade() -> None:
    # --- project_permissions: drop budget columns ---
    op.drop_column("project_permissions", "budget_alert_threshold")
    op.drop_column("project_permissions", "monthly_cost_budget_usd")
    op.drop_column("project_permissions", "daily_cost_budget_usd")

    # --- clients: restore secret columns ---
    # Re-add as nullable first so existing rows don't break, then set defaults
    op.add_column(
        "clients",
        sa.Column(
            "secret_prefix",
            sa.String(length=20),
            nullable=False,
            server_default="RESTORED",
        ),
    )
    op.add_column(
        "clients",
        sa.Column(
            "secret_hash",
            sa.String(length=128),
            nullable=False,
            server_default="RESTORED",
        ),
    )
    # Remove the server defaults after backfill (they were not in the original schema)
    op.alter_column("clients", "secret_prefix", server_default=None)
    op.alter_column("clients", "secret_hash", server_default=None)
