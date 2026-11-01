"""Context change reviews: the owner's keep, rework or refuse decisions on agent context changes.

Revision ID: e8b3d6f1a2c4
Revises: c4f7a2e9d815

One row per decision on one target (memory uuid, prompt slug or placement layer) through the revision the reviewer
saw (a revision id). The review queue is computed from revisions after each target's covered_until. New table only.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e8b3d6f1a2c4"
down_revision: str | Sequence[str] | None = "c4f7a2e9d815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "context_change_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("target_kind", sa.String(16), nullable=False),
        sa.Column("target_id", sa.String(200), nullable=False),
        sa.Column("through_revision", sa.String(36), nullable=False),
        sa.Column("result_revision", sa.String(36), nullable=True),
        sa.Column("covered_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("by", sa.String(100), nullable=True),
        sa.Column("by_kind", sa.String(16), nullable=True),
        sa.Column("by_session", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_context_change_reviews_target", "context_change_reviews",
                    ["target_kind", "target_id", "created_at"])
    op.create_index("ix_context_change_reviews_created_at", "context_change_reviews", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_context_change_reviews_created_at", table_name="context_change_reviews")
    op.drop_index("ix_context_change_reviews_target", table_name="context_change_reviews")
    op.drop_table("context_change_reviews")
