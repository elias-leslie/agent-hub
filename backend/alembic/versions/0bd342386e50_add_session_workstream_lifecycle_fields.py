"""add_session_workstream_lifecycle_fields

Revision ID: 0bd342386e50
Revises: f82cc6edc54a
Create Date: 2026-03-07 08:34:23.200278

Persist explicit lifecycle metadata for task/workstream lanes so persona
can mark sessions as authoritative, superseded, or retired.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0bd342386e50"
down_revision: str | Sequence[str] | None = "f82cc6edc54a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    workstream_status_enum = sa.Enum(
        "authoritative",
        "superseded",
        "retired",
        name="workstream_status_enum",
    )
    workstream_status_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "sessions",
        sa.Column("workstream_status", workstream_status_enum, nullable=True),
    )
    op.add_column("sessions", sa.Column("workstream_note", sa.Text(), nullable=True))
    op.add_column(
        "sessions",
        sa.Column("workstream_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("sessions", "workstream_updated_at")
    op.drop_column("sessions", "workstream_note")
    op.drop_column("sessions", "workstream_status")
    sa.Enum(name="workstream_status_enum").drop(op.get_bind(), checkfirst=True)
