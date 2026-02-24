"""drop_dead_tables_neo4j_cleanup

Revision ID: ff9d19d2c6d1
Revises: d3e4f5g6h7i8
Create Date: 2026-02-24 11:47:47.111664

Drop dead tables left over from the Neo4j -> PostgreSQL migration:
  - memory_entity_mentions (junction table, no longer used)
  - memory_entities (entity extraction, no longer used)
  - persona_journal (orphaned, journals now use the memories table)
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ff9d19d2c6d1"
down_revision: Union[str, Sequence[str], None] = "d3e4f5g6h7i8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop in FK-safe order: junction table first, then parent tables.
    op.execute("DROP TABLE IF EXISTS memory_entity_mentions")
    op.execute("DROP TABLE IF EXISTS memory_entities")
    op.execute("DROP TABLE IF EXISTS persona_journal")


def downgrade() -> None:
    # --- Recreate memory_entities (from d3e4f5g6h7i8) ---
    op.create_table(
        "memory_entities",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("scope", sa.String(100), nullable=False, server_default="global"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("mention_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "uq_memory_entities_name_scope",
        "memory_entities",
        ["name", "scope"],
        unique=True,
    )

    # --- Recreate memory_entity_mentions (from d3e4f5g6h7i8) ---
    op.create_table(
        "memory_entity_mentions",
        sa.Column(
            "memory_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("memories.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "entity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("memory_entities.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_index(
        "idx_memory_entity_mentions_entity",
        "memory_entity_mentions",
        ["entity_id"],
    )

    # --- Recreate persona_journal (from c4d5e6f7g8h9) ---
    op.create_table(
        "persona_journal",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "persona_id",
            sa.Integer(),
            sa.ForeignKey("persona.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "entry_date",
            sa.Date(),
            nullable=False,
            server_default=sa.text("CURRENT_DATE"),
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "entry_type",
            sa.String(50),
            nullable=False,
            server_default="observation",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_persona_journal_persona_date",
        "persona_journal",
        ["persona_id", sa.text("entry_date DESC")],
    )
