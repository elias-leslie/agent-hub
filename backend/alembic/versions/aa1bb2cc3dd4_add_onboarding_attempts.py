"""add_onboarding_attempts_column

Revision ID: aa1bb2cc3dd4
Revises: ff9d19d2c6d1
Create Date: 2026-02-24 12:00:00.000000

Adds onboarding_attempts column to persona table for tracking
rejection cycles and auto-approving after max attempts.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "aa1bb2cc3dd4"
down_revision: str | Sequence[str] | None = "ff9d19d2c6d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "persona",
        sa.Column("onboarding_attempts", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("persona", "onboarding_attempts")
