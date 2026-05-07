"""add_routing_canary_percent

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-05-07 21:05:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: str | None = "d0e1f2a3b4c5"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "agent_workload_routing_modes",
        sa.Column("canary_percent", sa.Float(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("agent_workload_routing_modes", "canary_percent")
