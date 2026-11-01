"""Per-session peak context and compaction count on usage_sessions.

Revision ID: b5e1c8a2d703
Revises: 7d2c9e4b1a60

Both are filled from usage_calls by services/context_observability/growth.py. NULL means no calls to read
(Pi and Agent Hub sessions), never zero. Additive nullable columns only.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b5e1c8a2d703"
down_revision: str | Sequence[str] | None = "7d2c9e4b1a60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("usage_sessions", sa.Column("peak_context_tokens", sa.BigInteger(), nullable=True))
    op.add_column("usage_sessions", sa.Column("compaction_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("usage_sessions", "compaction_count")
    op.drop_column("usage_sessions", "peak_context_tokens")
