from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a0a088ae8f03'
down_revision: str | Sequence[str] | None = 'ca45411429f5'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "memories",
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )

    op.create_table(
        "memory_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("memory_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("memories.id", ondelete="SET NULL"), nullable=True),
        sa.Column("memory_uuid", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("memory_type", sa.String(length=20), nullable=False),
        sa.Column("scope", sa.String(length=100), nullable=False),
        sa.Column("scope_id", sa.String(length=100), nullable=True),
        sa.Column("group_id", sa.String(length=100), nullable=True),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.Column("source_description", sa.Text(), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.String()), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("tier", sa.SmallInteger(), nullable=False),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("auto_inject", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("trigger_task_types", postgresql.ARRAY(sa.String()), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("trigger_phases", postgresql.ARRAY(sa.String()), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("valid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("changed_by", sa.String(length=100), nullable=True),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_memory_revisions_memory_uuid", "memory_revisions", ["memory_uuid"])
    op.create_index("ix_memory_revisions_action", "memory_revisions", ["action"])
    op.create_index("ix_memory_revisions_memory_id", "memory_revisions", ["memory_id"])
    op.create_index(
        "ix_memory_revisions_memory_uuid_created",
        "memory_revisions",
        ["memory_uuid", "created_at"],
    )

    op.execute(
        """
        INSERT INTO memory_revisions (
            memory_id,
            memory_uuid,
            version,
            action,
            content,
            name,
            summary,
            memory_type,
            scope,
            scope_id,
            group_id,
            source,
            source_description,
            tags,
            tier,
            pinned,
            auto_inject,
            display_order,
            trigger_task_types,
            trigger_phases,
            token_count,
            status,
            metadata,
            valid_at,
            content_hash,
            changed_by,
            change_reason,
            created_at
        )
        SELECT
            id,
            id::text,
            1,
            'snapshot',
            content,
            name,
            summary,
            memory_type,
            scope,
            scope_id,
            group_id,
            source,
            source_description,
            COALESCE(tags, '{}'::text[]),
            tier,
            pinned,
            auto_inject,
            COALESCE(display_order, 50),
            COALESCE(trigger_task_types, '{}'::text[]),
            COALESCE(trigger_phases, '{}'::text[]),
            token_count,
            status,
            COALESCE(metadata, '{}'::jsonb),
            valid_at,
            md5(content),
            'migration',
            'Backfilled current memory state when memory revisions launched',
            COALESCE(updated_at, created_at, now())
        FROM memories
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_memory_revisions_memory_uuid_created", table_name="memory_revisions")
    op.drop_index("ix_memory_revisions_memory_id", table_name="memory_revisions")
    op.drop_index("ix_memory_revisions_action", table_name="memory_revisions")
    op.drop_index("ix_memory_revisions_memory_uuid", table_name="memory_revisions")
    op.drop_table("memory_revisions")
    op.drop_column("memories", "version")
