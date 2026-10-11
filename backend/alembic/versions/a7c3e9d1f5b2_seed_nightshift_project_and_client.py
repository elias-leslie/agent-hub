"""seed nightshift project permission and service client

Revision ID: a7c3e9d1f5b2
Revises: c4d8e2f6a9b1
Create Date: 2026-10-11 19:00:00.000000

Nightshift (the host steward) calls /api/complete for its teacher chain and posts its externally billed model calls to
/api/analytics/costs/ingest. It gets its own read-tier project with a small completion budget and its own service
client restricted to that project. The client id is generated here, not committed: the deployment copies it into
Nightshift's secret reference (NIGHTSHIFT_AGENT_HUB_CLIENT_ID in ~/.env.local, mode 0600).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7c3e9d1f5b2"
down_revision: str | Sequence[str] | None = "c4d8e2f6a9b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROJECT_ID = "nightshift"
_ROOT_PATH = "/srv/workspaces/projects/nightshift"
_CLIENT_NAME = "nightshift"
# Teacher calls are a few batched classifications a night, usually on subscription routes ($0 marginal).
# The budget guards against a fallback onto a paid model.
_MONTHLY_BUDGET_USD = 1.0
_BUDGET_ALERT_THRESHOLD = 0.8


def upgrade() -> None:
    conn = op.get_bind()

    if not conn.execute(
        sa.text("SELECT 1 FROM project_permissions WHERE project_id = :p"), {"p": _PROJECT_ID}
    ).scalar():
        conn.execute(
            sa.text(
                """
                INSERT INTO project_permissions (
                    project_id, permission_tier, auto_exec_enabled, execution_start_hour, execution_end_hour,
                    root_path, daily_cost_budget_usd, monthly_cost_budget_usd, budget_alert_threshold
                ) VALUES (:p, 'read', false, 0, 24, :root, NULL, :monthly, :threshold)
                """
            ),
            {"p": _PROJECT_ID, "root": _ROOT_PATH, "monthly": _MONTHLY_BUDGET_USD, "threshold": _BUDGET_ALERT_THRESHOLD},
        )

    if not conn.execute(
        sa.text("SELECT 1 FROM clients WHERE display_name = :n AND client_type = 'service'"), {"n": _CLIENT_NAME}
    ).scalar():
        conn.execute(
            sa.text(
                """
                INSERT INTO clients (id, display_name, client_type, status, allowed_projects)
                VALUES (:id, :n, 'service', 'active', :allowed)
                """
            ),
            {"id": str(uuid.uuid4()), "n": _CLIENT_NAME, "allowed": json.dumps([_PROJECT_ID])},
        )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM clients WHERE display_name = :n AND client_type = 'service'"), {"n": _CLIENT_NAME})
    conn.execute(
        sa.text(
            """
            DELETE FROM project_permissions
            WHERE project_id = :p AND permission_tier = 'read' AND root_path = :root
              AND monthly_cost_budget_usd = :monthly AND daily_cost_budget_usd IS NULL
            """
        ),
        {"p": _PROJECT_ID, "root": _ROOT_PATH, "monthly": _MONTHLY_BUDGET_USD},
    )
