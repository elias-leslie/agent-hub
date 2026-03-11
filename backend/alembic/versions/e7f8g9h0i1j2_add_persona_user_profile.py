"""Add structured persona user_profile field.

Revision ID: e7f8g9h0i1j2
Revises: 6c39f1c7c8f3
Create Date: 2026-03-11 16:20:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7f8g9h0i1j2"
down_revision: str | Sequence[str] | None = "6c39f1c7c8f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "persona",
        sa.Column("user_profile", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("persona", "user_profile")
