"""add agent benchmark tracking

Revision ID: 10d42965cd8e
Revises: a8257e5c28c8
Create Date: 2026-03-11 11:29:56.428321

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '10d42965cd8e'
down_revision: str | Sequence[str] | None = 'a8257e5c28c8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "agent_benchmark_runs",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("benchmark_id", sa.String(length=100), nullable=False),
        sa.Column("agent_slug", sa.String(length=100), nullable=False),
        sa.Column("project_id", sa.String(length=100), nullable=False),
        sa.Column("suite_id", sa.String(length=100), nullable=False),
        sa.Column("run_kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="completed"),
        sa.Column("models", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("case_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("runs_per_case", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("use_memory", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("avg_score", sa.Float(), nullable=True),
        sa.Column("pass_rate", sa.Float(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("passed_attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("infra_failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("config_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("benchmark_id", name="agent_benchmark_runs_benchmark_id_key"),
    )
    op.create_index("ix_agent_benchmark_runs_benchmark_id", "agent_benchmark_runs", ["benchmark_id"])
    op.create_index("ix_agent_benchmark_runs_agent_slug", "agent_benchmark_runs", ["agent_slug"])
    op.create_index("ix_agent_benchmark_runs_project_id", "agent_benchmark_runs", ["project_id"])
    op.create_index("ix_agent_benchmark_runs_suite_id", "agent_benchmark_runs", ["suite_id"])
    op.create_index("ix_agent_benchmark_runs_run_kind", "agent_benchmark_runs", ["run_kind"])
    op.create_index(
        "ix_agent_benchmark_runs_agent_suite_completed",
        "agent_benchmark_runs",
        ["agent_slug", "suite_id", "completed_at"],
    )

    op.create_table(
        "agent_benchmark_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("benchmark_run_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("agent_benchmark_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_slug", sa.String(length=100), nullable=False),
        sa.Column("model_id", sa.String(length=200), nullable=False),
        sa.Column("effective_model", sa.String(length=200), nullable=True),
        sa.Column("requested_model", sa.String(length=200), nullable=True),
        sa.Column("case_id", sa.String(length=100), nullable=False),
        sa.Column("run_number", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.String(length=100), nullable=True),
        sa.Column("provider", sa.String(length=100), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("turns", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tool_calls_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("used_tool_names", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("schema_valid", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("tool_requirement_met", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("correctness_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("composite_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("passed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("infra_failure", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("failure_kind", sa.String(length=20), nullable=True),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.Column("fallback_used", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("primary_action", sa.String(length=32), nullable=True),
        sa.Column("should_dispatch", sa.Boolean(), nullable=True),
        sa.Column("should_close", sa.Boolean(), nullable=True),
        sa.Column("confidence", sa.String(length=16), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("raw_content", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_agent_benchmark_attempts_agent_slug", "agent_benchmark_attempts", ["agent_slug"])
    op.create_index("ix_agent_benchmark_attempts_model_id", "agent_benchmark_attempts", ["model_id"])
    op.create_index("ix_agent_benchmark_attempts_case_id", "agent_benchmark_attempts", ["case_id"])
    op.create_index(
        "ix_agent_benchmark_attempts_run_case",
        "agent_benchmark_attempts",
        ["benchmark_run_id", "case_id"],
    )
    op.create_index(
        "ix_agent_benchmark_attempts_agent_model_created",
        "agent_benchmark_attempts",
        ["agent_slug", "model_id", "created_at"],
    )

    op.create_table(
        "agent_regression_clusters",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("agent_slug", sa.String(length=100), nullable=False),
        sa.Column("suite_id", sa.String(length=100), nullable=False),
        sa.Column("regression_key", sa.String(length=255), nullable=False),
        sa.Column("case_id", sa.String(length=100), nullable=False),
        sa.Column("failure_detail", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("first_seen_run_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("agent_benchmark_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("last_seen_run_id", postgresql.UUID(as_uuid=False), sa.ForeignKey("agent_benchmark_runs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latest_avg_score", sa.Float(), nullable=True),
        sa.Column("affected_models", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("agent_slug", "suite_id", "regression_key", name="uq_agent_regression_clusters_agent_suite_key"),
    )
    op.create_index("ix_agent_regression_clusters_agent_slug", "agent_regression_clusters", ["agent_slug"])
    op.create_index("ix_agent_regression_clusters_suite_id", "agent_regression_clusters", ["suite_id"])
    op.create_index("ix_agent_regression_clusters_case_id", "agent_regression_clusters", ["case_id"])
    op.create_index("ix_agent_regression_clusters_status", "agent_regression_clusters", ["status"])
    op.create_index(
        "ix_agent_regression_clusters_agent_suite_status",
        "agent_regression_clusters",
        ["agent_slug", "suite_id", "status"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_agent_regression_clusters_agent_suite_status", table_name="agent_regression_clusters")
    op.drop_index("ix_agent_regression_clusters_status", table_name="agent_regression_clusters")
    op.drop_index("ix_agent_regression_clusters_case_id", table_name="agent_regression_clusters")
    op.drop_index("ix_agent_regression_clusters_suite_id", table_name="agent_regression_clusters")
    op.drop_index("ix_agent_regression_clusters_agent_slug", table_name="agent_regression_clusters")
    op.drop_table("agent_regression_clusters")

    op.drop_index("ix_agent_benchmark_attempts_agent_model_created", table_name="agent_benchmark_attempts")
    op.drop_index("ix_agent_benchmark_attempts_run_case", table_name="agent_benchmark_attempts")
    op.drop_index("ix_agent_benchmark_attempts_case_id", table_name="agent_benchmark_attempts")
    op.drop_index("ix_agent_benchmark_attempts_model_id", table_name="agent_benchmark_attempts")
    op.drop_index("ix_agent_benchmark_attempts_agent_slug", table_name="agent_benchmark_attempts")
    op.drop_table("agent_benchmark_attempts")

    op.drop_index("ix_agent_benchmark_runs_agent_suite_completed", table_name="agent_benchmark_runs")
    op.drop_index("ix_agent_benchmark_runs_run_kind", table_name="agent_benchmark_runs")
    op.drop_index("ix_agent_benchmark_runs_suite_id", table_name="agent_benchmark_runs")
    op.drop_index("ix_agent_benchmark_runs_project_id", table_name="agent_benchmark_runs")
    op.drop_index("ix_agent_benchmark_runs_agent_slug", table_name="agent_benchmark_runs")
    op.drop_index("ix_agent_benchmark_runs_benchmark_id", table_name="agent_benchmark_runs")
    op.drop_table("agent_benchmark_runs")
