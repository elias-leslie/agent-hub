"""add_summary_git_digest_to_sessions

Revision ID: y2z3a4b5c6d7
Revises: x1y2z3a4b5c6
Create Date: 2026-02-12 12:00:00.000000

Adds summary_git_digest TEXT column to sessions table for storing
condensed git commit context extracted during summary generation.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "y2z3a4b5c6d7"
down_revision: str | Sequence[str] | None = "f6h7i8j9k0l1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("summary_git_digest", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("sessions", "summary_git_digest")
