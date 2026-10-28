"""Allow a workflow step to end as cancelled.

Revision ID: c5e8a2b6d4f7
Revises: b4d7f1a9c2e6
Create Date: 2026-10-28
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c5e8a2b6d4f7"
down_revision: str | Sequence[str] | None = "b4d7f1a9c2e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BEFORE = "status IN ('pending','running','completed','failed','refused','needs_owner','skipped')"
_AFTER = "status IN ('pending','running','completed','failed','refused','needs_owner','skipped','cancelled')"


def upgrade() -> None:
    op.drop_constraint("ck_workflow_steps_status", "workflow_steps", type_="check")
    op.create_check_constraint("ck_workflow_steps_status", "workflow_steps", _AFTER)


def downgrade() -> None:
    op.execute("UPDATE workflow_steps SET status = 'skipped' WHERE status = 'cancelled'")
    op.drop_constraint("ck_workflow_steps_status", "workflow_steps", type_="check")
    op.create_check_constraint("ck_workflow_steps_status", "workflow_steps", _BEFORE)
