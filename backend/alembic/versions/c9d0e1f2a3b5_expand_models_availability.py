"""expand_models_availability

Revision ID: c9d0e1f2a3b5
Revises: c9d0e1f2a3b4
Create Date: 2026-05-07 18:55:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c9d0e1f2a3b5"
down_revision: str | Sequence[str] | None = "c9d0e1f2a3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "models",
        "availability",
        existing_type=sa.String(length=50),
        type_=sa.String(length=200),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "models",
        "availability",
        existing_type=sa.String(length=200),
        type_=sa.String(length=50),
        existing_nullable=True,
    )
