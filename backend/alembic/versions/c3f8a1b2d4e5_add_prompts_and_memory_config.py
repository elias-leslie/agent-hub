"""add_prompts_and_memory_config

Revision ID: c3f8a1b2d4e5
Revises: b5c6d7e8f9a0
Create Date: 2026-02-07 00:00:00.000000

Creates prompts + agent_prompts tables for DB-backed prompt composition,
and adds memory_config JSON column to agents for per-agent memory curation.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3f8a1b2d4e5"
down_revision: str | Sequence[str] | None = "b5c6d7e8f9a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create prompts tables and add agents.memory_config."""
    op.create_table(
        "prompts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("slug", sa.String(100), unique=True, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_global",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_prompts_slug", "prompts", ["slug"], unique=True)
    op.create_index(
        "ix_prompts_is_global",
        "prompts",
        ["is_global"],
        postgresql_where=sa.text("is_global = true"),
    )

    op.create_table(
        "agent_prompts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "agent_id",
            sa.Integer(),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "prompt_id",
            sa.Integer(),
            sa.ForeignKey("prompts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(100), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("agent_id", "prompt_id", name="uq_agent_prompts_agent_id_prompt_id"),
    )
    op.create_index("ix_agent_prompts_agent_id", "agent_prompts", ["agent_id"])
    op.create_index("ix_agent_prompts_role", "agent_prompts", ["role"])

    op.add_column(
        "agents",
        sa.Column("memory_config", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    """Drop prompts tables and agents.memory_config."""
    op.drop_column("agents", "memory_config")
    op.drop_index("ix_agent_prompts_role", table_name="agent_prompts")
    op.drop_index("ix_agent_prompts_agent_id", table_name="agent_prompts")
    op.drop_table("agent_prompts")
    op.drop_index("ix_prompts_is_global", table_name="prompts")
    op.drop_index("ix_prompts_slug", table_name="prompts")
    op.drop_table("prompts")
