"""add_model_enrichments_table

Revision ID: bb2cc3dd4ee5
Revises: aa1bb2cc3dd4
Create Date: 2026-02-24 13:00:00.000000

Adds model_enrichments table for storing external benchmark data
as overlay on the static MODEL_CATALOG.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "bb2cc3dd4ee5"
down_revision: str | Sequence[str] | None = "aa1bb2cc3dd4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_enrichments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("model_id", sa.String(200), nullable=False),
        sa.Column("ext_coding", sa.Integer(), nullable=True),
        sa.Column("ext_reasoning", sa.Integer(), nullable=True),
        sa.Column("ext_speed_tier", sa.String(20), nullable=True),
        sa.Column("ext_input_per_m", sa.Float(), nullable=True),
        sa.Column("ext_output_per_m", sa.Float(), nullable=True),
        sa.Column("raw_benchmark_data", postgresql.JSONB(), nullable=True),
        sa.Column("source", sa.String(100), server_default="models.dev", nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_model_enrichments"),
        sa.UniqueConstraint("model_id", name="uq_model_enrichments_model_id"),
    )
    op.create_index("ix_model_enrichments_model_id", "model_enrichments", ["model_id"])
    op.create_index("ix_model_enrichments_synced_at", "model_enrichments", ["synced_at"])


def downgrade() -> None:
    op.drop_index("ix_model_enrichments_synced_at", table_name="model_enrichments")
    op.drop_index("ix_model_enrichments_model_id", table_name="model_enrichments")
    op.drop_table("model_enrichments")
