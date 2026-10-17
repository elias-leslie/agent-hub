"""add models.subscription_rates

Revision ID: e6b1c8d4a2f9
Revises: d2f7a9c3e6b4
Create Date: 2026-10-17 12:00:00.000000

Per-model subscription pricing facts move from code into the catalog row: Codex credit
rates ({"credits_per_m": {"input", "cached_input", "output"}}) and Claude's long-prompt
multiplier ({"long_prompt": {"over_tokens", "multiplier"}}). Schema only; values are set
through the models API and exported to the seed.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e6b1c8d4a2f9"
down_revision: str | Sequence[str] | None = "d2f7a9c3e6b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("models", sa.Column("subscription_rates", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("models", "subscription_rates")
