"""add benchmark experiments

Revision ID: 29e5dc2c0921
Revises: 10d42965cd8e
Create Date: 2026-03-11 12:22:13.882043

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '29e5dc2c0921'
down_revision: Union[str, Sequence[str], None] = '10d42965cd8e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "agent_benchmark_experiments",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("experiment_key", sa.String(length=120), nullable=False),
        sa.Column("agent_slug", sa.String(length=100), nullable=False),
        sa.Column("project_id", sa.String(length=100), nullable=False),
        sa.Column("suite_id", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("hypothesis", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("decision", sa.String(length=20), nullable=False, server_default="hold"),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("baseline_label", sa.String(length=60), nullable=False, server_default="baseline"),
        sa.Column("candidate_label", sa.String(length=60), nullable=False, server_default="candidate"),
        sa.Column("min_runs_per_cohort", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("experiment_key", name="agent_benchmark_experiments_experiment_key_key"),
    )
    op.create_index(
        "ix_agent_benchmark_experiments_experiment_key",
        "agent_benchmark_experiments",
        ["experiment_key"],
    )
    op.create_index(
        "ix_agent_benchmark_experiments_agent_slug",
        "agent_benchmark_experiments",
        ["agent_slug"],
    )
    op.create_index(
        "ix_agent_benchmark_experiments_project_id",
        "agent_benchmark_experiments",
        ["project_id"],
    )
    op.create_index(
        "ix_agent_benchmark_experiments_suite_id",
        "agent_benchmark_experiments",
        ["suite_id"],
    )
    op.create_index(
        "ix_agent_benchmark_experiments_status",
        "agent_benchmark_experiments",
        ["status"],
    )
    op.create_index(
        "ix_agent_benchmark_experiments_agent_suite_created",
        "agent_benchmark_experiments",
        ["agent_slug", "suite_id", "created_at"],
    )

    op.add_column(
        "agent_benchmark_runs",
        sa.Column(
            "experiment_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("agent_benchmark_experiments.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "agent_benchmark_runs",
        sa.Column("experiment_cohort", sa.String(length=20), nullable=True),
    )
    op.create_index(
        "ix_agent_benchmark_runs_experiment_id",
        "agent_benchmark_runs",
        ["experiment_id"],
    )
    op.create_index(
        "ix_agent_benchmark_runs_experiment_cohort",
        "agent_benchmark_runs",
        ["experiment_cohort"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_agent_benchmark_runs_experiment_cohort", table_name="agent_benchmark_runs")
    op.drop_index("ix_agent_benchmark_runs_experiment_id", table_name="agent_benchmark_runs")
    op.drop_column("agent_benchmark_runs", "experiment_cohort")
    op.drop_column("agent_benchmark_runs", "experiment_id")

    op.drop_index(
        "ix_agent_benchmark_experiments_agent_suite_created",
        table_name="agent_benchmark_experiments",
    )
    op.drop_index("ix_agent_benchmark_experiments_status", table_name="agent_benchmark_experiments")
    op.drop_index("ix_agent_benchmark_experiments_suite_id", table_name="agent_benchmark_experiments")
    op.drop_index("ix_agent_benchmark_experiments_project_id", table_name="agent_benchmark_experiments")
    op.drop_index("ix_agent_benchmark_experiments_agent_slug", table_name="agent_benchmark_experiments")
    op.drop_index("ix_agent_benchmark_experiments_experiment_key", table_name="agent_benchmark_experiments")
    op.drop_table("agent_benchmark_experiments")
