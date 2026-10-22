"""Allow native Pi sessions in the persisted session type enum.

Revision ID: e3a7c9d1f502
Revises: d4f2a6c8e0b1
Create Date: 2026-10-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e3a7c9d1f502"
down_revision: str | Sequence[str] | None = "d4f2a6c8e0b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE session_type_enum ADD VALUE IF NOT EXISTS 'pi'")


def downgrade() -> None:
    """Keep the additive value so existing native session history stays readable."""
    pass
