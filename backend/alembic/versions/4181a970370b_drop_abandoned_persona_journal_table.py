"""drop abandoned persona_journal table

Revision ID: 4181a970370b
Revises: 65a08072c8a0
Create Date: 2026-03-02 10:07:08.029471

The persona_journal table was created in c4d5e6f7g8h9 but journal entries
now live in the unified memory system (memories table with scope='agent:persona'
and memory_type='journal').  The table was already dropped at the DB level by
ff9d19d2c6d1, but this migration formalises the removal and keeps the
downgrade path self-contained.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4181a970370b"
down_revision: str | Sequence[str] | None = "65a08072c8a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Safe no-op if the table was already dropped by ff9d19d2c6d1.
    op.execute("DROP TABLE IF EXISTS persona_journal")


def downgrade() -> None:
    # Recreate the table exactly as defined in c4d5e6f7g8h9.
    op.create_table(
        "persona_journal",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "persona_id",
            sa.Integer(),
            sa.ForeignKey("persona.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "entry_date",
            sa.Date(),
            nullable=False,
            server_default=sa.text("CURRENT_DATE"),
        ),
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
