"""add memory context routing fields

Revision ID: 0ff5fb2a634c
Revises: 93da76ab0d27
Create Date: 2026-03-25 21:07:17.778800

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0ff5fb2a634c'
down_revision: str | Sequence[str] | None = '93da76ab0d27'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "memories",
        sa.Column(
            "context_kind",
            sa.String(length=32),
            nullable=False,
            server_default="reference",
        ),
    )
    op.add_column(
        "memories",
        sa.Column(
            "applicability",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "memory_revisions",
        sa.Column(
            "context_kind",
            sa.String(length=32),
            nullable=False,
            server_default="reference",
        ),
    )
    op.add_column(
        "memory_revisions",
        sa.Column(
            "applicability",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.execute(
        """
        UPDATE memories
        SET context_kind = CASE
            WHEN lower(COALESCE(memory_type, '')) = 'continuity' THEN 'continuity'
            WHEN lower(COALESCE(memory_type, '')) IN ('feedback', 'journal') THEN 'signal'
            WHEN tier IN (1, 2) THEN 'policy'
            ELSE 'reference'
        END
        """
    )
    op.execute(
        """
        UPDATE memory_revisions
        SET context_kind = CASE
            WHEN lower(COALESCE(memory_type, '')) = 'continuity' THEN 'continuity'
            WHEN lower(COALESCE(memory_type, '')) IN ('feedback', 'journal') THEN 'signal'
            WHEN tier IN (1, 2) THEN 'policy'
            ELSE 'reference'
        END
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("memory_revisions", "applicability")
    op.drop_column("memory_revisions", "context_kind")
    op.drop_column("memories", "applicability")
    op.drop_column("memories", "context_kind")
