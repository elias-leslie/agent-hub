"""Add rich evidence fields to agent benchmark attempts.

Revision ID: 3c4d5e6f7081
Revises: 2b3c4d5e6f70
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "3c4d5e6f7081"
down_revision: str | None = "2b3c4d5e6f70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("agent_benchmark_attempts", sa.Column("task_family", sa.String(64), nullable=True))
    op.add_column("agent_benchmark_attempts", sa.Column("harness_arm", sa.String(32), nullable=True))
    op.add_column(
        "agent_benchmark_attempts",
        sa.Column("dimension_scores", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
    )
    op.add_column(
        "agent_benchmark_attempts",
        sa.Column("runtime_metrics", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
    )
    op.add_column(
        "agent_benchmark_attempts",
        sa.Column("safety_failures", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
    )
    op.add_column(
        "agent_benchmark_attempts",
        sa.Column("oracle_details", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
    )
    op.add_column(
        "agent_benchmark_attempts",
        sa.Column("artifact_identity", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
    )
    op.create_index(
        "ix_agent_benchmark_attempts_task_family",
        "agent_benchmark_attempts",
        ["task_family"],
        unique=False,
    )
    op.create_index(
        "ix_agent_benchmark_attempts_harness_arm",
        "agent_benchmark_attempts",
        ["harness_arm"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_agent_benchmark_attempts_harness_arm", table_name="agent_benchmark_attempts")
    op.drop_index("ix_agent_benchmark_attempts_task_family", table_name="agent_benchmark_attempts")
    op.drop_column("agent_benchmark_attempts", "artifact_identity")
    op.drop_column("agent_benchmark_attempts", "oracle_details")
    op.drop_column("agent_benchmark_attempts", "safety_failures")
    op.drop_column("agent_benchmark_attempts", "runtime_metrics")
    op.drop_column("agent_benchmark_attempts", "dimension_scores")
    op.drop_column("agent_benchmark_attempts", "harness_arm")
    op.drop_column("agent_benchmark_attempts", "task_family")
