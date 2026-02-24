"""add_agent_performance_logs_table

Revision ID: cc3dd4ee5ff6
Revises: bb2cc3dd4ee5
Create Date: 2026-02-24 13:01:00.000000

Adds agent_performance_logs table for tracking agent/model performance
observations filed by Jenny, system automation, or humans.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "cc3dd4ee5ff6"
down_revision: str | Sequence[str] | None = "bb2cc3dd4ee5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_performance_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("agent_slug", sa.String(100), nullable=False),
        sa.Column("model_id", sa.String(200), nullable=False),
        sa.Column("task_type", sa.String(50), nullable=True),
        sa.Column("project_id", sa.String(100), nullable=True),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("feedback_type", sa.String(20), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("tool_calls_count", sa.Integer(), nullable=True),
        sa.Column("turns", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("session_id", sa.String(100), nullable=True),
        sa.Column("logged_by", sa.String(20), server_default="persona", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_agent_performance_logs"),
    )
    op.create_index("ix_agent_perf_agent_created", "agent_performance_logs", ["agent_slug", "created_at"])
    op.create_index("ix_agent_perf_model_created", "agent_performance_logs", ["model_id", "created_at"])
    op.create_index("ix_agent_perf_agent_model_type", "agent_performance_logs", ["agent_slug", "model_id", "task_type"])
    op.create_index("ix_agent_perf_feedback_type", "agent_performance_logs", ["feedback_type"])


def downgrade() -> None:
    op.drop_index("ix_agent_perf_feedback_type", table_name="agent_performance_logs")
    op.drop_index("ix_agent_perf_agent_model_type", table_name="agent_performance_logs")
    op.drop_index("ix_agent_perf_model_created", table_name="agent_performance_logs")
    op.drop_index("ix_agent_perf_agent_created", table_name="agent_performance_logs")
    op.drop_table("agent_performance_logs")
