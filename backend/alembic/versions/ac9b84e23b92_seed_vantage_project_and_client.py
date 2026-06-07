"""seed vantage project and client

Revision ID: ac9b84e23b92
Revises: 375d38ecdc2e
Create Date: 2026-03-27 15:15:00.000000

"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ac9b84e23b92"
down_revision: str | Sequence[str] | None = "375d38ecdc2e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VANTAGE_PROJECT_ID = "vantage"
_VANTAGE_ROOT_PATH = "/home/demo/projects/vantage"
_VANTAGE_CLIENT_ID = "876c5159-95c3-45fa-abbd-ac39d4d42bfc"
_VANTAGE_ALLOWED_PROJECTS = json.dumps([_VANTAGE_PROJECT_ID])
_DAILY_BUDGET_USD = 10.0
_MONTHLY_BUDGET_USD = 100.0
_BUDGET_ALERT_THRESHOLD = 0.8


def _row_exists(conn: sa.Connection, sql: str, params: dict[str, object]) -> bool:
    return bool(conn.execute(sa.text(sql), params).scalar())


def upgrade() -> None:
    """Seed the Vantage execution project and its dedicated service client."""
    conn = op.get_bind()

    project_exists = _row_exists(
        conn,
        "SELECT 1 FROM project_permissions WHERE project_id = :project_id",
        {"project_id": _VANTAGE_PROJECT_ID},
    )
    if not project_exists:
        conn.execute(
            sa.text(
                """
                INSERT INTO project_permissions (
                    project_id,
                    permission_tier,
                    auto_exec_enabled,
                    execution_start_hour,
                    execution_end_hour,
                    root_path,
                    daily_cost_budget_usd,
                    monthly_cost_budget_usd,
                    budget_alert_threshold
                ) VALUES (
                    :project_id,
                    :permission_tier,
                    :auto_exec_enabled,
                    :execution_start_hour,
                    :execution_end_hour,
                    :root_path,
                    :daily_cost_budget_usd,
                    :monthly_cost_budget_usd,
                    :budget_alert_threshold
                )
                """
            ),
            {
                "project_id": _VANTAGE_PROJECT_ID,
                "permission_tier": "read",
                "auto_exec_enabled": False,
                "execution_start_hour": 0,
                "execution_end_hour": 24,
                "root_path": _VANTAGE_ROOT_PATH,
                "daily_cost_budget_usd": _DAILY_BUDGET_USD,
                "monthly_cost_budget_usd": _MONTHLY_BUDGET_USD,
                "budget_alert_threshold": _BUDGET_ALERT_THRESHOLD,
            },
        )

    client_exists = _row_exists(
        conn,
        "SELECT 1 FROM clients WHERE id = :client_id",
        {"client_id": _VANTAGE_CLIENT_ID},
    )
    if not client_exists:
        conn.execute(
            sa.text(
                """
                INSERT INTO clients (
                    id,
                    display_name,
                    client_type,
                    status,
                    rate_limit_rpm,
                    rate_limit_tpm,
                    allowed_projects
                ) VALUES (
                    :client_id,
                    :display_name,
                    :client_type,
                    :status,
                    :rate_limit_rpm,
                    :rate_limit_tpm,
                    :allowed_projects
                )
                """
            ),
            {
                "client_id": _VANTAGE_CLIENT_ID,
                "display_name": "vantage",
                "client_type": "service",
                "status": "active",
                "rate_limit_rpm": 60,
                "rate_limit_tpm": 100000,
                "allowed_projects": _VANTAGE_ALLOWED_PROJECTS,
            },
        )


def downgrade() -> None:
    """Remove seeded Vantage bootstrap rows added by this migration."""
    conn = op.get_bind()

    conn.execute(
        sa.text("DELETE FROM clients WHERE id = :client_id"),
        {"client_id": _VANTAGE_CLIENT_ID},
    )
    conn.execute(
        sa.text(
            """
            DELETE FROM project_permissions
            WHERE project_id = :project_id
              AND permission_tier = 'read'
              AND auto_exec_enabled = false
              AND execution_start_hour = 0
              AND execution_end_hour = 24
              AND root_path = :root_path
              AND daily_cost_budget_usd = :daily_cost_budget_usd
              AND monthly_cost_budget_usd = :monthly_cost_budget_usd
              AND budget_alert_threshold = :budget_alert_threshold
            """
        ),
        {
            "project_id": _VANTAGE_PROJECT_ID,
            "root_path": _VANTAGE_ROOT_PATH,
            "daily_cost_budget_usd": _DAILY_BUDGET_USD,
            "monthly_cost_budget_usd": _MONTHLY_BUDGET_USD,
            "budget_alert_threshold": _BUDGET_ALERT_THRESHOLD,
        },
    )
