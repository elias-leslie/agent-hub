"""add_memory_review_and_fingerprints

Revision ID: a7c9d3e5f1b2
Revises: e9f0a1b2c3d4
Create Date: 2026-04-26 09:35:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c9d3e5f1b2"
down_revision: str | Sequence[str] | None = "e9f0a1b2c3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.add_column("memories", sa.Column("content_fingerprint", sa.String(64), nullable=True))
    op.add_column(
        "memories",
        sa.Column("review_status", sa.String(20), nullable=False, server_default="pending"),
    )
    op.add_column(
        "memories",
        sa.Column("sensitivity_tier", sa.String(20), nullable=False, server_default="normal"),
    )
    op.add_column("memories", sa.Column("last_reviewed_at", sa.DateTime(timezone=True), nullable=True))

    op.execute(
        """
        UPDATE memories
           SET content_fingerprint = encode(
               digest(lower(btrim(regexp_replace(content, '\\s+', ' ', 'g'))), 'sha256'),
               'hex'
           )
         WHERE content_fingerprint IS NULL
        """
    )

    op.create_index(
        "idx_memories_content_fingerprint",
        "memories",
        ["content_fingerprint"],
    )
    op.create_index("idx_memories_review_status", "memories", ["review_status"])
    op.create_index(
        "idx_memories_review_due",
        "memories",
        ["status", "last_reviewed_at", "created_at"],
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_memories_text_search
        ON memories USING gin (
            to_tsvector(
                'english',
                coalesce(name, '') || ' ' || coalesce(summary, '') || ' ' || coalesce(content, '')
            )
        )
        """
    )

    op.create_table(
        "memory_review_runs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("reviewer_agent_slug", sa.String(100), nullable=False),
        sa.Column("reviewer_model_id", sa.String(200), nullable=True),
        sa.Column("batch_limit", sa.Integer(), nullable=False),
        sa.Column("reviewed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("needs_action_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        CREATE INDEX idx_memory_review_runs_started_at
        ON memory_review_runs (started_at DESC)
        """
    )
    op.create_index(
        "idx_memory_review_runs_status",
        "memory_review_runs",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("idx_memory_review_runs_status", table_name="memory_review_runs")
    op.drop_index("idx_memory_review_runs_started_at", table_name="memory_review_runs")
    op.drop_table("memory_review_runs")
    op.execute("DROP INDEX IF EXISTS idx_memories_text_search")
    op.drop_index("idx_memories_review_due", table_name="memories")
    op.drop_index("idx_memories_review_status", table_name="memories")
    op.drop_index("idx_memories_content_fingerprint", table_name="memories")
    op.drop_column("memories", "last_reviewed_at")
    op.drop_column("memories", "sensitivity_tier")
    op.drop_column("memories", "review_status")
    op.drop_column("memories", "content_fingerprint")
