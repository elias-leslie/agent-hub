"""add lifecycle columns

Revision ID: c8113ded1ed2
Revises: e2a476ce0825
Create Date: 2026-02-28 18:00:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "c8113ded1ed2"
down_revision = "e2a476ce0825"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- memories table: lifecycle columns ---
    op.add_column(
        "memories",
        sa.Column("lifecycle_score", sa.Float(), nullable=True),
    )
    op.add_column(
        "memories",
        sa.Column(
            "lifecycle_score_updated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "memories",
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "memories",
        sa.Column(
            "superseded_by",
            UUID(as_uuid=True),
            nullable=True,
        ),
    )
    # Index for retirement queries (finding stale archives)
    op.create_index(
        "ix_memories_lifecycle_score",
        "memories",
        ["lifecycle_score"],
        postgresql_where=sa.text("status = 'active'"),
    )
    # FK for superseded_by (self-referential)
    op.create_foreign_key(
        "fk_memories_superseded_by",
        "memories",
        "memories",
        ["superseded_by"],
        ["id"],
        ondelete="SET NULL",
    )

    # --- tier_change_log: lifecycle score tracking + metadata ---
    op.add_column(
        "tier_change_log",
        sa.Column("lifecycle_score_before", sa.Float(), nullable=True),
    )
    op.add_column(
        "tier_change_log",
        sa.Column("lifecycle_score_after", sa.Float(), nullable=True),
    )
    op.add_column(
        "tier_change_log",
        sa.Column(
            "metadata",
            JSONB(),
            server_default="{}",
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("tier_change_log", "metadata")
    op.drop_column("tier_change_log", "lifecycle_score_after")
    op.drop_column("tier_change_log", "lifecycle_score_before")
    op.drop_constraint("fk_memories_superseded_by", "memories", type_="foreignkey")
    op.drop_index("ix_memories_lifecycle_score", table_name="memories")
    op.drop_column("memories", "superseded_by")
    op.drop_column("memories", "retired_at")
    op.drop_column("memories", "lifecycle_score_updated_at")
    op.drop_column("memories", "lifecycle_score")
