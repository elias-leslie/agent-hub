"""Retire authoring style policy; retain benchmark history as generic metadata.

Existing policy configuration is archived by the operator before rollout.
Downgrade restores the schema defaults; restore custom values from that archive.
"""

import sqlalchemy as sa

from alembic import op

revision = "0c78d126e3ab"
down_revision = "fa6e931d24c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE sessions
        SET provider_metadata = COALESCE(provider_metadata::jsonb, '{}'::jsonb)
            || '{"session_kind": "benchmark"}'::jsonb
        WHERE request_source LIKE 'manual/caveman%'
          AND NOT COALESCE(provider_metadata::jsonb, '{}'::jsonb) ? 'session_kind'
    """)
    op.drop_table("compactness_policy")


def downgrade() -> None:
    op.create_table(
        "compactness_policy",
        sa.Column("id", sa.Integer(), primary_key=True),
        *[
            sa.Column(name, sa.Integer(), nullable=False, server_default=str(default))
            for name, default in (
                ("memory_max_chars", 280),
                ("memory_max_lines", 4),
                ("prompt_max_tokens", 350),
                ("prompt_max_lines", 80),
                ("max_sentence_words", 24),
                ("max_avg_sentence_words", 16),
                ("avg_sentence_min_words", 120),
                ("max_article_ratio_permille", 85),
                ("article_ratio_min_words", 80),
            )
        ],
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("id = 1", name="compactness_policy_singleton"),
    )
    op.execute("INSERT INTO compactness_policy (id) VALUES (1)")
