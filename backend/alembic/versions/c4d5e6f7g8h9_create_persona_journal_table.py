"""create_persona_journal_table

Revision ID: c4d5e6f7g8h9
Revises: b3c4d5e6f7g8
Create Date: 2026-02-21 23:00:00.000000

Creates the persona_journal table for daily journal entries that
provide temporal continuity for the persona.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4d5e6f7g8h9"
down_revision: str | Sequence[str] | None = "b3c4d5e6f7g8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "persona_journal",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "persona_id",
            sa.Integer(),
            sa.ForeignKey("persona.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entry_date", sa.Date(), nullable=False, server_default=sa.text("CURRENT_DATE")),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "entry_type",
            sa.String(50),
            nullable=False,
            server_default="observation",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_persona_journal_persona_date",
        "persona_journal",
        ["persona_id", sa.text("entry_date DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_persona_journal_persona_date", table_name="persona_journal")
    op.drop_table("persona_journal")
