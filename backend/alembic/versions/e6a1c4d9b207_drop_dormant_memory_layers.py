"""Drop the dormant memory side-layer data.

Revision ID: e6a1c4d9b207
Revises: b5d2c8e1f7a3

The code that wrote these (review agent, tier optimizer, lifecycle scoring) was deleted in
b7ce9704a; the owner approved dropping the data. Downgrade recreates the empty schema only.

- memory_review_runs and tier_change_log tables
- memories.lifecycle_score and lifecycle_score_updated_at (with ix_memories_lifecycle_score)
- the two disabled workflow_schedule_controls rows of the deleted tier_optimizer and
  memory_cleanup schedules
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e6a1c4d9b207"
down_revision: str | Sequence[str] | None = "b5d2c8e1f7a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DELETED_SCHEDULES = ("tier_optimizer", "memory_cleanup")


def upgrade() -> None:
    op.execute(
        sa.text("DELETE FROM workflow_schedule_controls WHERE schedule_id IN :ids AND enabled = false")
        .bindparams(sa.bindparam("ids", _DELETED_SCHEDULES, expanding=True))
    )
    op.drop_table("memory_review_runs")  # its indexes go with it
    op.drop_table("tier_change_log")
    op.drop_index("ix_memories_lifecycle_score", table_name="memories")
    op.drop_column("memories", "lifecycle_score_updated_at")
    op.drop_column("memories", "lifecycle_score")


def downgrade() -> None:
    op.add_column("memories", sa.Column("lifecycle_score", sa.Float(), nullable=True))
    op.add_column("memories", sa.Column("lifecycle_score_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_memories_lifecycle_score", "memories", ["lifecycle_score"],
        postgresql_where=sa.text("status::text = 'active'"),
    )
    op.create_table(
        "tier_change_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("episode_uuid", sa.String(length=36), nullable=False),
        sa.Column("old_tier", sa.String(length=20), nullable=False),
        sa.Column("new_tier", sa.String(length=20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("change_type", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("lifecycle_score_before", sa.Float(), nullable=True),
        sa.Column("lifecycle_score_after", sa.Float(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=True),
        sa.PrimaryKeyConstraint("id", name="tier_change_log_pkey"),
    )
    op.create_index("ix_tier_change_log_episode_uuid", "tier_change_log", ["episode_uuid"])
    op.create_index("ix_tier_change_log_created_at", "tier_change_log", ["created_at"])
    op.create_table(
        "memory_review_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="running", nullable=False),
        sa.Column("reviewer_agent_slug", sa.String(length=100), nullable=False),
        sa.Column("reviewer_model_id", sa.String(length=200), nullable=True),
        sa.Column("batch_limit", sa.Integer(), nullable=False),
        sa.Column("reviewed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("needs_action_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("dry_run", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_memory_review_runs"),
    )
    op.execute("CREATE INDEX idx_memory_review_runs_started_at ON memory_review_runs (started_at DESC)")
    op.create_index("idx_memory_review_runs_status", "memory_review_runs", ["status"])
