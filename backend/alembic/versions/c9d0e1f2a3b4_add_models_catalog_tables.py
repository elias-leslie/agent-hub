"""add_models_catalog_tables

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-05-07 18:45:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: str | Sequence[str] | None = "b8c9d0e1f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "models",
        sa.Column("id", sa.String(length=200), nullable=False),
        sa.Column("alias", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("hint", sa.String(length=200), server_default="", nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("score_coding", sa.Integer(), nullable=False),
        sa.Column("score_reasoning", sa.Integer(), nullable=False),
        sa.Column("score_planning", sa.Integer(), nullable=False),
        sa.Column("score_tool_use", sa.Integer(), nullable=False),
        sa.Column("score_instruction", sa.Integer(), nullable=False),
        sa.Column("score_design", sa.Integer(), nullable=False),
        sa.Column("cost_input_per_m", sa.Float(), nullable=False),
        sa.Column("cost_output_per_m", sa.Float(), nullable=False),
        sa.Column("pricing_unit", sa.String(length=50), server_default="per_million_tokens", nullable=False),
        sa.Column("unit_price", sa.Float(), nullable=True),
        sa.Column("service_tiers", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("cache_read_per_million", sa.Float(), nullable=True),
        sa.Column("cache_write_per_million", sa.Float(), nullable=True),
        sa.Column("context_window", sa.Integer(), nullable=False),
        sa.Column("speed_tier", sa.String(length=20), nullable=False),
        sa.Column("can_generate_images", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("has_vision", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("can_edit_images", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("has_thinking", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("supports_pdf", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("supports_audio", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("supports_tool_execution", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("supports_verbosity", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("supports_xhigh", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("supports_session_cache", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False),
        sa.Column("release_date", sa.String(length=40), nullable=True),
        sa.Column("knowledge_cutoff", sa.String(length=40), nullable=True),
        sa.Column("family", sa.String(length=100), nullable=True),
        sa.Column("availability", sa.String(length=200), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("source", sa.String(length=50), server_default="seed", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_models")),
    )
    op.create_index(op.f("ix_models_provider"), "models", ["provider"], unique=False)
    op.create_index("ix_models_provider_active", "models", ["provider", "is_active"], unique=False)
    op.create_index("ix_models_sort_order", "models", ["sort_order"], unique=False)

    op.create_table(
        "model_aliases",
        sa.Column("alias", sa.String(length=200), nullable=False),
        sa.Column("model_id", sa.String(length=200), nullable=False),
        sa.Column("alias_type", sa.String(length=50), server_default="manual", nullable=False),
        sa.Column("source", sa.String(length=50), server_default="seed", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["model_id"], ["models.id"], name=op.f("fk_model_aliases_models_model_id"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("alias", name=op.f("pk_model_aliases")),
    )
    op.create_index(op.f("ix_model_aliases_model_id"), "model_aliases", ["model_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_model_aliases_model_id"), table_name="model_aliases")
    op.drop_table("model_aliases")
    op.drop_index("ix_models_sort_order", table_name="models")
    op.drop_index("ix_models_provider_active", table_name="models")
    op.drop_index(op.f("ix_models_provider"), table_name="models")
    op.drop_table("models")
