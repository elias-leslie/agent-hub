"""restore_global_instructions_and_tier_change_log

Revision ID: 73c82f4ebcc5
Revises: 1d642bcb1f01
Create Date: 2026-02-02 19:20:16.652588

Restores tables that were incorrectly dropped in cb33d77516d8.
These tables have active code references:
- global_instructions: Used by agent_routing.py, has frontend UI (GlobalInstructionsPanel.tsx)
- tier_change_log: Used by tier_operations.py, tier_corrections.py for audit logging
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "73c82f4ebcc5"
down_revision: str | Sequence[str] | None = "1d642bcb1f01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Restore accidentally dropped tables."""
    # Restore global_instructions table
    op.create_table(
        "global_instructions",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("scope", sa.VARCHAR(length=100), nullable=False),
        sa.Column(
            "content",
            sa.TEXT(),
            server_default=sa.text("''::text"),
            nullable=False,
        ),
        sa.Column(
            "enabled",
            sa.BOOLEAN(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="global_instructions_pkey"),
    )
    op.create_index("ix_global_instructions_scope", "global_instructions", ["scope"], unique=True)

    # Insert default global scope row
    op.execute(
        """
        INSERT INTO global_instructions (scope, content, enabled)
        VALUES ('global', '', true)
        """
    )

    # Restore tier_change_log table
    op.create_table(
        "tier_change_log",
        sa.Column("id", sa.INTEGER(), autoincrement=True, nullable=False),
        sa.Column("episode_uuid", sa.VARCHAR(length=36), nullable=False),
        sa.Column("old_tier", sa.VARCHAR(length=20), nullable=False),
        sa.Column("new_tier", sa.VARCHAR(length=20), nullable=False),
        sa.Column("reason", sa.TEXT(), nullable=False),
        sa.Column("change_type", sa.VARCHAR(length=20), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="tier_change_log_pkey"),
    )
    op.create_index(
        "ix_tier_change_log_episode_uuid", "tier_change_log", ["episode_uuid"], unique=False
    )
    op.create_index(
        "ix_tier_change_log_created_at", "tier_change_log", ["created_at"], unique=False
    )


def downgrade() -> None:
    """Drop the restored tables."""
    op.drop_index("ix_tier_change_log_created_at", table_name="tier_change_log")
    op.drop_index("ix_tier_change_log_episode_uuid", table_name="tier_change_log")
    op.drop_table("tier_change_log")
    op.drop_index("ix_global_instructions_scope", table_name="global_instructions")
    op.drop_table("global_instructions")
