"""cost_logs cache + compression telemetry columns

Adds cache-read/write token columns and tool-result compression stats to
``cost_logs`` so flag-on vs flag-off measurement (Headroom compression Phase 5)
can compare token AND cache deltas, plus per-row compression attribution.

Revision ID: c4a1b2d3e5f6
Revises: a2d4f6b8c0e1
Create Date: 2026-06-08
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4a1b2d3e5f6"
down_revision: str | Sequence[str] | None = "a2d4f6b8c0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_COLUMNS = (
    "cache_read_tokens",
    "cache_write_tokens",
    "compression_blocks",
    "compression_tokens_before",
    "compression_tokens_after",
)


def upgrade() -> None:
    for name in _COLUMNS:
        op.add_column(
            "cost_logs",
            sa.Column(name, sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    for name in reversed(_COLUMNS):
        op.drop_column("cost_logs", name)
