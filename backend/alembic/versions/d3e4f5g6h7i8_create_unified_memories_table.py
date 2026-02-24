"""create_unified_memories_table

Revision ID: d3e4f5g6h7i8
Revises: c2d3e4f5g6h7
Create Date: 2026-02-24 10:00:00.000000

Creates the unified memories table with pgvector support, replacing Neo4j/Graphiti.
Also creates memory_entities and memory_entity_mentions tables.

Prerequisites:
  pgvector extension must be enabled: CREATE EXTENSION IF NOT EXISTS vector;
  (requires superuser — run manually if migration fails)
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d3e4f5g6h7i8"
down_revision: str | Sequence[str] | None = "c2d3e4f5g6h7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Ensure pgvector extension exists (requires superuser to have pre-created it)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # --- memories table (raw SQL for pgvector column type) ---
    op.execute("""
        CREATE TABLE memories (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            content TEXT NOT NULL,
            name VARCHAR(500),
            summary TEXT,
            embedding vector(768),

            -- Classification
            memory_type VARCHAR(20) NOT NULL,
            scope VARCHAR(100) NOT NULL DEFAULT 'global',
            scope_id VARCHAR(100),
            group_id VARCHAR(100),
            source VARCHAR(100),
            source_description TEXT,
            tags TEXT[],

            -- Tier system
            tier SMALLINT NOT NULL DEFAULT 3,
            pinned BOOLEAN NOT NULL DEFAULT FALSE,
            auto_inject BOOLEAN NOT NULL DEFAULT FALSE,
            display_order INTEGER DEFAULT 50,

            -- Conditional injection
            trigger_task_types TEXT[],
            trigger_phases TEXT[],

            -- Usage tracking
            loaded_count INTEGER NOT NULL DEFAULT 0,
            referenced_count INTEGER NOT NULL DEFAULT 0,
            helpful_count INTEGER NOT NULL DEFAULT 0,
            harmful_count INTEGER NOT NULL DEFAULT 0,

            -- Lifecycle
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            token_count INTEGER,

            -- Demotion tracking
            demoted_at TIMESTAMPTZ,
            demotion_reason VARCHAR(200),

            -- Type-specific metadata
            metadata JSONB DEFAULT '{}',

            -- Reference time
            valid_at TIMESTAMPTZ,

            -- Timestamps
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_accessed_at TIMESTAMPTZ
        )
    """)

    # Indexes for memories
    op.execute("""
        CREATE INDEX idx_memories_scope_tier
        ON memories (scope, tier, status)
        WHERE status = 'active'
    """)
    op.execute("""
        CREATE INDEX idx_memories_type_scope
        ON memories (memory_type, scope)
        WHERE status = 'active'
    """)
    op.execute("""
        CREATE INDEX idx_memories_group_id
        ON memories (group_id)
        WHERE group_id IS NOT NULL
    """)
    op.execute("CREATE INDEX idx_memories_created_at ON memories (created_at)")
    op.execute("CREATE INDEX idx_memories_metadata ON memories USING gin (metadata)")
    op.execute("""
        CREATE INDEX idx_memories_embedding
        ON memories USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 64)
    """)

    # --- memory_entities table ---
    op.create_table(
        "memory_entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("scope", sa.String(100), nullable=False, server_default="global"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("mention_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("uq_memory_entities_name_scope", "memory_entities", ["name", "scope"], unique=True)

    # --- memory_entity_mentions table ---
    op.create_table(
        "memory_entity_mentions",
        sa.Column("memory_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("memories.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("memory_entities.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_index("idx_memory_entity_mentions_entity", "memory_entity_mentions", ["entity_id"])


def downgrade() -> None:
    op.drop_table("memory_entity_mentions")
    op.drop_table("memory_entities")
    op.execute("DROP TABLE IF EXISTS memories")
