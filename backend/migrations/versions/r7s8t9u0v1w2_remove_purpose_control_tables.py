"""remove_purpose_control_tables

Revision ID: r7s8t9u0v1w2
Revises: q6r7s8t9u0v1
Create Date: 2026-01-28

Remove dead PurposeControl infrastructure:
- purpose_controls table
- client_purpose_controls table

These tables were never used - no UI was built for them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "r7s8t9u0v1w2"
down_revision: str | None = "q6r7s8t9u0v1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop purpose_controls and client_purpose_controls tables."""
    # Drop client_purpose_controls first (no FK but good practice)
    op.drop_index("ix_client_purpose_controls_combo", table_name="client_purpose_controls")
    op.drop_index("ix_client_purpose_controls_purpose", table_name="client_purpose_controls")
    op.drop_index("ix_client_purpose_controls_client_name", table_name="client_purpose_controls")
    op.drop_table("client_purpose_controls")

    # Drop purpose_controls
    op.drop_index("ix_purpose_controls_purpose", table_name="purpose_controls")
    op.drop_table("purpose_controls")


def downgrade() -> None:
    """Restore purpose_controls and client_purpose_controls tables."""
    # Recreate purpose_controls
    op.create_table(
        "purpose_controls",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(length=100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("disabled_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("disabled_by", sa.String(length=100), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_purpose_controls_purpose", "purpose_controls", ["purpose"], unique=True)

    # Recreate client_purpose_controls
    op.create_table(
        "client_purpose_controls",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("client_name", sa.String(length=100), nullable=False),
        sa.Column("purpose", sa.String(length=100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("disabled_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("disabled_by", sa.String(length=100), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_client_purpose_controls_client_name", "client_purpose_controls", ["client_name"]
    )
    op.create_index("ix_client_purpose_controls_purpose", "client_purpose_controls", ["purpose"])
    op.create_index(
        "ix_client_purpose_controls_combo", "client_purpose_controls", ["client_name", "purpose"]
    )
