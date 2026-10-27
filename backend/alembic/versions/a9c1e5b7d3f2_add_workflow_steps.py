"""Add workflow session type and the workflow_steps ledger.

Revision ID: a9c1e5b7d3f2
Revises: e20c973d117c
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a9c1e5b7d3f2"
down_revision: str | Sequence[str] | None = "e20c973d117c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE session_type_enum ADD VALUE IF NOT EXISTS 'workflow'")
    op.create_table(
        "workflow_steps",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "run_session_id",
            sa.String(36),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("step_key", sa.String(100), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("definition", postgresql.JSONB, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("restarts", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "current_attempt_session_id",
            sa.String(36),
            sa.ForeignKey("sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("chosen_model", sa.String(200), nullable=True),
        sa.Column("handoff", postgresql.JSONB, nullable=True),
        sa.Column("checkpoint_sha", sa.String(64), nullable=True),
        sa.Column("outcome", postgresql.JSONB, nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_id", sa.String(200), nullable=True, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("run_session_id", "step_key", name="uq_workflow_steps_run_key"),
        sa.UniqueConstraint("run_session_id", "position", name="uq_workflow_steps_run_position"),
        sa.CheckConstraint(
            "status IN ('pending','running','completed','failed','refused','needs_owner','skipped')",
            name="ck_workflow_steps_status",
        ),
    )
    op.create_index(
        "ix_workflow_steps_status_heartbeat", "workflow_steps", ["status", "heartbeat_at"]
    )
    op.create_index(
        "ix_workflow_steps_current_attempt", "workflow_steps", ["current_attempt_session_id"]
    )


def downgrade() -> None:
    op.drop_table("workflow_steps")
