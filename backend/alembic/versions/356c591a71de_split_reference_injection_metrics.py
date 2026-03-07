"""split reference injection metrics

Revision ID: 356c591a71de
Revises: 0bd342386e50
Create Date: 2026-03-07 17:02:14.380384

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '356c591a71de'
down_revision: str | Sequence[str] | None = '0bd342386e50'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "memory_injection_metrics",
        sa.Column("reference_selected_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "memory_injection_metrics",
        sa.Column("reference_index_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "memory_injection_metrics",
        sa.Column("reference_cited_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "memory_injection_metrics",
        sa.Column("reference_selected_uuids", sa.JSON(), nullable=True),
    )
    op.add_column(
        "memory_injection_metrics",
        sa.Column("reference_index_uuids", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("memory_injection_metrics", "reference_index_uuids")
    op.drop_column("memory_injection_metrics", "reference_selected_uuids")
    op.drop_column("memory_injection_metrics", "reference_cited_count")
    op.drop_column("memory_injection_metrics", "reference_index_count")
    op.drop_column("memory_injection_metrics", "reference_selected_count")
