"""add persona execution state

Revision ID: 706345626a08
Revises: cf39a0bccadf
Create Date: 2026-03-10 10:26:14.152218

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '706345626a08'
down_revision: str | Sequence[str] | None = 'cf39a0bccadf'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "persona",
        sa.Column(
            "execution_state",
            sa.String(length=16),
            nullable=False,
            server_default="active",
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("persona", "execution_state")
