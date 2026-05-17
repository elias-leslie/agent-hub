"""prune_stale_runtime_context_overrides

Revision ID: u5v6w7x8y9z0
Revises: t5u6v7w8x9y0
Create Date: 2026-05-17 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "u5v6w7x8y9z0"
down_revision: str | Sequence[str] | None = "t5u6v7w8x9y0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM runtime_context_overrides r
        WHERE r.source_type = 'memory'
          AND NOT EXISTS (
              SELECT 1
              FROM memories m
              WHERE m.id::text = r.source_id
                AND m.status = 'active'
          )
        """
    )
    op.execute(
        """
        DELETE FROM runtime_context_overrides r
        WHERE r.source_type = 'prompt'
          AND NOT EXISTS (
              SELECT 1
              FROM prompts p
              WHERE p.slug = r.source_id
                AND p.enabled IS TRUE
          )
        """
    )


def downgrade() -> None:
    # Data pruning is intentionally irreversible.
    pass
