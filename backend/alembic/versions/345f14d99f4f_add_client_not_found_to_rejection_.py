"""add client_not_found to rejection_reason_enum

Revision ID: 345f14d99f4f
Revises: 536346caeff9
Create Date: 2026-02-25 23:11:32.793959

"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '345f14d99f4f'
down_revision: str | Sequence[str] | None = '536346caeff9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE rejection_reason_enum ADD VALUE IF NOT EXISTS 'client_not_found'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; no-op.
    pass
