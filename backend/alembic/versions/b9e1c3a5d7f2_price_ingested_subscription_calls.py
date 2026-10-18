"""price ingested subscription calls that arrived without a list price

Revision ID: b9e1c3a5d7f2
Revises: a8d2f4c6e1b3
Create Date: 2026-10-18 15:20:00.000000

Nightshift's planner ingested Claude subscription calls before it sent api_equiv_usd, so the
Costs page counted them as $0. Price those rows from their tokens (cache writes at the 1-hour rate, as Nightshift prices them); ingest now does the same.
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "b9e1c3a5d7f2"
down_revision: str | Sequence[str] | None = "a8d2f4c6e1b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Superseded by d4f2a6c8e0b1: the model catalog is not loaded during migrations, so this priced nothing."""


def downgrade() -> None:
    """Prices derived from tokens stay; they were never cash."""
