"""Expand credentials.provider length for hidden system namespaces.

Revision ID: d60cd02141c5
Revises: a0a088ae8f03
Create Date: 2026-03-13 16:49:13.894576
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d60cd02141c5"
down_revision: str | Sequence[str] | None = "a0a088ae8f03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Allow longer provider namespaces in encrypted credential storage."""
    op.alter_column(
        "credentials",
        "provider",
        existing_type=sa.String(length=20),
        type_=sa.String(length=100),
        existing_nullable=False,
    )


def downgrade() -> None:
    """Restore the old provider length if all values still fit."""
    conn = op.get_bind()
    too_long_provider = conn.execute(
        sa.text(
            "SELECT provider FROM credentials WHERE char_length(provider) > 20 ORDER BY provider LIMIT 1"
        )
    ).scalar_one_or_none()
    if too_long_provider is not None:
        raise RuntimeError(
            "Cannot downgrade credentials.provider to VARCHAR(20) while longer provider IDs exist: "
            f"{too_long_provider}"
        )

    op.alter_column(
        "credentials",
        "provider",
        existing_type=sa.String(length=100),
        type_=sa.String(length=20),
        existing_nullable=False,
    )
