"""Index automation runs by status and time.

Revision ID: b7d2e4f6a8c0
Revises: a2c6e8f0b4d1

Run history's "Failures only" filter and the profiles' unreviewed-failure
count select runs by status, newest first.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b7d2e4f6a8c0"
down_revision: str | Sequence[str] | None = "a2c6e8f0b4d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_automation_runs_status_created", "automation_runs", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_automation_runs_status_created", table_name="automation_runs")
