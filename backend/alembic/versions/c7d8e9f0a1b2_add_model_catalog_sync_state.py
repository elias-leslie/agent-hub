"""add_model_catalog_sync_state

Revision ID: c7d8e9f0a1b2
Revises: 4b7a9c1d2e3f, z3a4b5c6d7e8
Create Date: 2026-04-14 16:40:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "c7d8e9f0a1b2"
down_revision = ("4b7a9c1d2e3f", "z3a4b5c6d7e8")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_catalog_sync_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="never", nullable=False),
        sa.Column("source_counts", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("discovery_summary", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("model_catalog_sync_state")
