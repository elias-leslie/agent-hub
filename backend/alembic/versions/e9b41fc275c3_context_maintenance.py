"""Shared context maintenance queue and explicit attention receipts.

Revision ID: e9b41fc275c3
Revises: d8a30ef164b2
"""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "e9b41fc275c3"
down_revision = "d8a30ef164b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("context_maintenance_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column("source_keys", postgresql.JSONB(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=False),
        sa.Column("evidence_ids", postgresql.JSONB(), nullable=False),
        sa.Column("detail", postgresql.JSONB(), nullable=False),
        sa.Column("claim_owner", sa.String(400), nullable=True),
        sa.Column("claim_session", sa.String(200), nullable=True),
        sa.Column("decision", sa.JSON(), nullable=False),
        sa.Column("resolution", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_context_maintenance_items_state", "context_maintenance_items", ["state"])
    op.create_index("ix_context_maintenance_items_sources", "context_maintenance_items", ["source_keys"], postgresql_using="gin")
    op.create_table("context_maintenance_ingest", sa.Column("record_id", sa.String(36), primary_key=True))
    op.create_table("context_maintenance_attention", sa.Column("session_key", sa.String(64), primary_key=True),
        sa.Column("acknowledged", sa.JSON(), nullable=False))


def downgrade() -> None:
    op.drop_table("context_maintenance_attention")
    op.drop_table("context_maintenance_ingest")
    op.drop_table("context_maintenance_items")
