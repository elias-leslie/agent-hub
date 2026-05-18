"""drop_agents_timeout_seconds

Removes the per-agent timeout_seconds column. Per the "no arbitrary timeouts"
mandate, agent execution turns are no longer bounded by a stored timeout.

Revision ID: v6w7x8y9z0a1
Revises: u5v6w7x8y9z0
Create Date: 2026-05-18 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "v6w7x8y9z0a1"
down_revision: str | Sequence[str] | None = "u5v6w7x8y9z0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("agents", "timeout_seconds")


def downgrade() -> None:
    op.add_column(
        "agents",
        sa.Column("timeout_seconds", sa.Float(), nullable=True),
    )
