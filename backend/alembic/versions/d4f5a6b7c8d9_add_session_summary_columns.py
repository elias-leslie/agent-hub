"""add_session_summary_columns

Revision ID: d4f5a6b7c8d9
Revises: c3f8a1b2d4e5
Create Date: 2026-02-11 00:00:00.000000

Adds summary columns to sessions table for structured session summary
storage. Replaces Neo4j episode storage with PostgreSQL-native storage.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4f5a6b7c8d9"
down_revision: str | Sequence[str] | None = "c3f8a1b2d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add session summary columns."""
    op.add_column("sessions", sa.Column("summary_oneliner", sa.Text(), nullable=True))
    op.add_column("sessions", sa.Column("summary_outcome", sa.String(20), nullable=True))
    op.add_column("sessions", sa.Column("summary_files_touched", sa.JSON(), nullable=True))
    op.add_column("sessions", sa.Column("summary_branch", sa.String(200), nullable=True))
    op.add_column(
        "sessions",
        sa.Column("summary_generated_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Index for continuity injection query: recent summaries by project + branch
    op.create_index(
        "ix_sessions_summary_lookup",
        "sessions",
        ["project_id", "summary_branch", "summary_generated_at"],
        postgresql_where=sa.text("summary_oneliner IS NOT NULL"),
    )


def downgrade() -> None:
    """Remove session summary columns."""
    op.drop_index("ix_sessions_summary_lookup", table_name="sessions")
    op.drop_column("sessions", "summary_generated_at")
    op.drop_column("sessions", "summary_branch")
    op.drop_column("sessions", "summary_files_touched")
    op.drop_column("sessions", "summary_outcome")
    op.drop_column("sessions", "summary_oneliner")
