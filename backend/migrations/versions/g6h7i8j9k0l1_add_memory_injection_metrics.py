"""add_memory_injection_metrics

Revision ID: g6h7i8j9k0l1
Revises: f0a1b2c3d4e5
Create Date: 2026-01-21 10:00:00.000000

Add memory_injection_metrics table for A/B testing and performance tracking.
Captures injection latency, counts per block, variant assignment, and citation tracking.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "g6h7i8j9k0l1"
down_revision: str | Sequence[str] | None = "f0a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create memory_injection_metrics table for A/B testing."""
    op.create_table(
        "memory_injection_metrics",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("external_id", sa.String(100), nullable=True),
        sa.Column("project_id", sa.String(100), nullable=True),
        # Performance metrics
        sa.Column("injection_latency_ms", sa.Integer(), nullable=True),
        # Injection counts per block
        sa.Column("mandates_count", sa.Integer(), nullable=False, default=0),
        sa.Column("guardrails_count", sa.Integer(), nullable=False, default=0),
        sa.Column("reference_count", sa.Integer(), nullable=False, default=0),
        sa.Column("total_tokens", sa.Integer(), nullable=False, default=0),
        # Query context
        sa.Column("query", sa.Text(), nullable=True),
        # A/B variant (BASELINE, ENHANCED, MINIMAL, AGGRESSIVE)
        sa.Column("variant", sa.String(20), nullable=False, default="BASELINE"),
        # Outcome tracking
        sa.Column("task_succeeded", sa.Boolean(), nullable=True),
        sa.Column("retries", sa.Integer(), nullable=True, default=0),
        # Citation tracking - JSON array of cited memory UUIDs
        sa.Column("memories_cited", sa.JSON(), nullable=True, default=list),
        # All memories loaded - JSON array of loaded memory UUIDs
        sa.Column("memories_loaded", sa.JSON(), nullable=True, default=list),
    )
    # Indexes for querying
    op.create_index(
        "ix_memory_injection_metrics_external_id",
        "memory_injection_metrics",
        ["external_id"],
    )
    op.create_index(
        "ix_memory_injection_metrics_variant",
        "memory_injection_metrics",
        ["variant"],
    )
    op.create_index(
        "ix_memory_injection_metrics_created_at",
        "memory_injection_metrics",
        ["created_at"],
    )
    op.create_index(
        "ix_memory_injection_metrics_project_id",
        "memory_injection_metrics",
        ["project_id"],
    )


def downgrade() -> None:
    """Drop memory_injection_metrics table."""
    op.drop_index("ix_memory_injection_metrics_project_id", table_name="memory_injection_metrics")
    op.drop_index("ix_memory_injection_metrics_created_at", table_name="memory_injection_metrics")
    op.drop_index("ix_memory_injection_metrics_variant", table_name="memory_injection_metrics")
    op.drop_index("ix_memory_injection_metrics_external_id", table_name="memory_injection_metrics")
    op.drop_table("memory_injection_metrics")
