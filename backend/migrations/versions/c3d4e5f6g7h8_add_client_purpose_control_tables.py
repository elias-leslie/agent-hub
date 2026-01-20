"""add_client_purpose_control_tables

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g7
Create Date: 2026-01-20 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6g7h8"
down_revision: str | Sequence[str] | None = "b2c3d4e5f6g7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create client_controls, purpose_controls, and client_purpose_controls tables."""
    # ClientControl table
    op.create_table(
        "client_controls",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("client_name", sa.String(100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("disabled_at", sa.DateTime(), nullable=True),
        sa.Column("disabled_by", sa.String(100), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_client_controls_client_name", "client_controls", ["client_name"], unique=True
    )

    # PurposeControl table
    op.create_table(
        "purpose_controls",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("purpose", sa.String(100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("disabled_at", sa.DateTime(), nullable=True),
        sa.Column("disabled_by", sa.String(100), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_purpose_controls_purpose", "purpose_controls", ["purpose"], unique=True)

    # ClientPurposeControl table
    op.create_table(
        "client_purpose_controls",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("client_name", sa.String(100), nullable=False),
        sa.Column("purpose", sa.String(100), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("disabled_at", sa.DateTime(), nullable=True),
        sa.Column("disabled_by", sa.String(100), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("client_name", "purpose", name="uq_client_purpose"),
    )
    op.create_index(
        "ix_client_purpose_controls_client_name", "client_purpose_controls", ["client_name"]
    )
    op.create_index("ix_client_purpose_controls_purpose", "client_purpose_controls", ["purpose"])
    op.create_index(
        "ix_client_purpose_controls_combo", "client_purpose_controls", ["client_name", "purpose"]
    )


def downgrade() -> None:
    """Drop client_controls, purpose_controls, and client_purpose_controls tables."""
    op.drop_index("ix_client_purpose_controls_combo", table_name="client_purpose_controls")
    op.drop_index("ix_client_purpose_controls_purpose", table_name="client_purpose_controls")
    op.drop_index("ix_client_purpose_controls_client_name", table_name="client_purpose_controls")
    op.drop_table("client_purpose_controls")

    op.drop_index("ix_purpose_controls_purpose", table_name="purpose_controls")
    op.drop_table("purpose_controls")

    op.drop_index("ix_client_controls_client_name", table_name="client_controls")
    op.drop_table("client_controls")
