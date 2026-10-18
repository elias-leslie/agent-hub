"""price ingested subscription calls that arrived without a list price, with the catalog loaded

Revision ID: d4f2a6c8e0b1
Revises: b9e1c3a5d7f2
Create Date: 2026-10-18 15:30:00.000000

Nightshift's planner ingested Claude subscription calls before it sent api_equiv_usd, so the
Costs page counted them as $0. Price those rows from their tokens (cache writes at the 1-hour
rate, as Nightshift prices them); ingest now does the same. Rates come from the DB model
catalog, which this migration loads first (the app normally loads it at startup).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.orm import Session

from alembic import op
from app.constants.catalog import replace_runtime_model_catalog
from app.models.model_catalog import ModelCatalogEntry
from app.services.model_catalog_service import row_to_model_entry
from app.services.subscription_accounting.rates import claude_api_equiv_usd

revision: str = "d4f2a6c8e0b1"
down_revision: str | Sequence[str] | None = "b9e1c3a5d7f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    entries = [row_to_model_entry(row) for row in Session(bind=bind).scalars(sa.select(ModelCatalogEntry))]
    replace_runtime_model_catalog(entries)
    rows = bind.execute(
        sa.text(
            "SELECT id, model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens FROM cost_logs "
            "WHERE billing_mode = 'subscription' AND api_equiv_usd IS NULL AND model LIKE 'claude-%'"
        )
    ).all()
    for row in rows:
        usd = claude_api_equiv_usd(
            row.model, input_tokens=row.input_tokens or 0, output_tokens=row.output_tokens or 0,
            cache_read=row.cache_read_tokens or 0, cache_write_1h=row.cache_write_tokens or 0,
        )
        if usd is not None:
            bind.execute(sa.text("UPDATE cost_logs SET api_equiv_usd = :usd WHERE id = :id"), {"usd": usd, "id": row.id})


def downgrade() -> None:
    """Prices derived from tokens stay; they were never cash."""
