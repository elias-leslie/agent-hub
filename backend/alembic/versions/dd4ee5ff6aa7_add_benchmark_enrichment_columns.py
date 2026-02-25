"""add_benchmark_enrichment_columns

Revision ID: dd4ee5ff6aa7
Revises: cc3dd4ee5ff6
Create Date: 2026-02-24 16:00:00.000000

Adds ext_tool_use, ext_planning, ext_instruction columns to model_enrichments
for BFCL and LiveBench benchmark data.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "dd4ee5ff6aa7"
down_revision: str | Sequence[str] | None = "cc3dd4ee5ff6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("model_enrichments", sa.Column("ext_tool_use", sa.Integer(), nullable=True))
    op.add_column("model_enrichments", sa.Column("ext_planning", sa.Integer(), nullable=True))
    op.add_column("model_enrichments", sa.Column("ext_instruction", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("model_enrichments", "ext_instruction")
    op.drop_column("model_enrichments", "ext_planning")
    op.drop_column("model_enrichments", "ext_tool_use")
