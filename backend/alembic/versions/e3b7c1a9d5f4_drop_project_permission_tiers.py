"""Drop the per-project permission tier, auto-exec switch and execution hours.

Agents get their tools from their own registry and autonomous runs are paused
through Automations, so project_permissions keeps only the project identity,
root path, cost budgets and alert threshold.
"""

import sqlalchemy as sa

from alembic import op

revision = "e3b7c1a9d5f4"
down_revision = "d6a9b3c7e2f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("project_permissions", "permission_tier")
    op.drop_column("project_permissions", "auto_exec_enabled")
    op.drop_column("project_permissions", "execution_start_hour")
    op.drop_column("project_permissions", "execution_end_hour")


def downgrade() -> None:
    op.add_column(
        "project_permissions",
        sa.Column("execution_end_hour", sa.Integer(), nullable=False, server_default="24"),
    )
    op.add_column(
        "project_permissions",
        sa.Column("execution_start_hour", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "project_permissions",
        sa.Column("auto_exec_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "project_permissions",
        sa.Column("permission_tier", sa.String(10), nullable=False, server_default="read"),
    )
