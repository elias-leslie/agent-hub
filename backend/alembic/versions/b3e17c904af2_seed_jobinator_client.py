"""seed jobinator-4000 client and correct its project root path

Revision ID: b3e17c904af2
Revises: c1d9e73a2b48
Create Date: 2026-09-03 14:10:00.000000

"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3e17c904af2"
down_revision: str | Sequence[str] | None = "c1d9e73a2b48"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PROJECT_ID = "jobinator-4000"
_CLIENT_ID = "ea338be9-55b1-4aa6-921e-6493014f6f8e"
_ALLOWED_PROJECTS = json.dumps([_PROJECT_ID])

# The project_permissions row was created with a workspace path that does not
# exist on this host; every other managed project lives under /srv.
_CORRECT_ROOT_PATH = "/srv/workspaces/projects/jobinator-4000"
_STALE_ROOT_PATH = "/home/kasadis/.local/share/summitflow/workspaces/projects/jobinator-4000"

# Jobinator's agents run on the Gemini free tier, so spend should sit at zero.
# The budget is a guard against an unnoticed fallback onto a paid model, not an
# expected cost.
_DAILY_BUDGET_USD = 5.0
_MONTHLY_BUDGET_USD = 50.0
_BUDGET_ALERT_THRESHOLD = 0.8


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        sa.text(
            """
            UPDATE project_permissions
            SET root_path = :correct_root_path,
                daily_cost_budget_usd = COALESCE(daily_cost_budget_usd, :daily),
                monthly_cost_budget_usd = COALESCE(monthly_cost_budget_usd, :monthly),
                budget_alert_threshold = COALESCE(budget_alert_threshold, :threshold)
            WHERE project_id = :project_id
              AND root_path = :stale_root_path
            """
        ),
        {
            "project_id": _PROJECT_ID,
            "correct_root_path": _CORRECT_ROOT_PATH,
            "stale_root_path": _STALE_ROOT_PATH,
            "daily": _DAILY_BUDGET_USD,
            "monthly": _MONTHLY_BUDGET_USD,
            "threshold": _BUDGET_ALERT_THRESHOLD,
        },
    )

    exists = conn.execute(
        sa.text("SELECT 1 FROM clients WHERE id = :client_id"),
        {"client_id": _CLIENT_ID},
    ).scalar()
    if not exists:
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
                "client_id": _CLIENT_ID,
                "display_name": "jobinator-4000",
                "client_type": "service",
                "status": "active",
                # Free-tier RPD is small and resets midnight Pacific. 60 rpm is
                # the house default; the nightly screening sweep caps itself.
                "rate_limit_rpm": 60,
                "rate_limit_tpm": 500000,
                "allowed_projects": _ALLOWED_PROJECTS,
            },
        )


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        sa.text("DELETE FROM clients WHERE id = :client_id"),
        {"client_id": _CLIENT_ID},
    )
    conn.execute(
        sa.text(
            """
            UPDATE project_permissions
            SET root_path = :stale_root_path
            WHERE project_id = :project_id
              AND root_path = :correct_root_path
            """
        ),
        {
            "project_id": _PROJECT_ID,
            "correct_root_path": _CORRECT_ROOT_PATH,
            "stale_root_path": _STALE_ROOT_PATH,
        },
    )
