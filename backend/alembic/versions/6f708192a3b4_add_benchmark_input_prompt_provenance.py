"""Add benchmark input and prompt provenance.

Revision ID: 6f708192a3b4
Revises: 5e6f708192a3
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "6f708192a3b4"
down_revision: str | Sequence[str] | None = "5e6f708192a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_benchmark_attempts",
        sa.Column("input_sha256", sa.String(64), nullable=True),
    )
    op.add_column(
        "agent_benchmark_attempts",
        sa.Column("prompt_revision", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("agent_benchmark_attempts", "prompt_revision")
    op.drop_column("agent_benchmark_attempts", "input_sha256")
