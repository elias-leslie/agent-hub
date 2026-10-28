"""Record where each subscription usage reading came from.

Revision ID: b4d7f1a9c2e6
Revises: a9c1e5b7d3f2
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b4d7f1a9c2e6"
down_revision: str | Sequence[str] | None = "a9c1e5b7d3f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("subscription_usage_snapshots", sa.Column("source", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("subscription_usage_snapshots", "source")
