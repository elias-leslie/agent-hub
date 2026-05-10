"""add_compactness_policy

Revision ID: m9n0o1p2q3r4
Revises: l8m9n0o1p2q3
Create Date: 2026-05-10 12:00:00.000000

Persists the strict-Caveman gate thresholds (memory char/line caps, prompt
token/line caps, sentence-length errors, article-ratio rules) that previously
lived as module-level constants in services/compactness.py. Singleton row
keyed on id=1 — the gate is global, not per-profile or per-kind.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "m9n0o1p2q3r4"
down_revision: str | Sequence[str] | None = "l8m9n0o1p2q3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "compactness_policy",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("memory_max_chars", sa.Integer(), nullable=False, server_default="280"),
        sa.Column("memory_max_lines", sa.Integer(), nullable=False, server_default="4"),
        sa.Column("prompt_max_tokens", sa.Integer(), nullable=False, server_default="350"),
        sa.Column("prompt_max_lines", sa.Integer(), nullable=False, server_default="80"),
        sa.Column("max_sentence_words", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("max_avg_sentence_words", sa.Integer(), nullable=False, server_default="16"),
        sa.Column("avg_sentence_min_words", sa.Integer(), nullable=False, server_default="120"),
        # Stored as integer permille (parts per thousand) so caps are
        # discrete and fit a plain integer column. 85 == 8.5%.
        sa.Column("max_article_ratio_permille", sa.Integer(), nullable=False, server_default="85"),
        sa.Column("article_ratio_min_words", sa.Integer(), nullable=False, server_default="80"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="compactness_policy_singleton"),
    )
    op.execute(
        """
        INSERT INTO compactness_policy (id) VALUES (1)
        """
    )


def downgrade() -> None:
    op.drop_table("compactness_policy")
