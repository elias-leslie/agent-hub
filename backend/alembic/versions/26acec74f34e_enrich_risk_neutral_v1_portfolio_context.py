"""enrich_risk_neutral_v1_portfolio_context

Revision ID: 26acec74f34e
Revises: cd9d123a7fb3
Create Date: 2026-05-18

The consolidated risk voter now receives ``portfolio_context`` with the
household's current concentration picture (sector exposure, top-5
positions, cash %). The CONSERVATIVE lens's "concentration / sector cap"
critique only lands if the prompt names the field — otherwise the model
falls back on the IPS result, which only checks the per-trade delta and
not the existing book.
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "26acec74f34e"
down_revision: str | Sequence[str] | None = "cd9d123a7fb3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_OLD_INPUTS = (
    "You are given:\n"
    "- The trader's proposal (action, qty_pct, entry, stop, horizon, rationale)\n"
    "- The full analyst reports + debate transcript\n"
    "- The IPS check results (concentration, tax-bill, sector-exposure, wash-sale)"
)
_NEW_INPUTS = (
    "You are given:\n"
    "- The trader's proposal (action, qty_pct, entry, stop, horizon, rationale)\n"
    "- The full analyst reports + debate transcript\n"
    "- The IPS check results (concentration, tax-bill, sector-exposure, wash-sale)\n"
    "- `portfolio_context` for the household: `position_in_symbol`, `sector_exposure_pct`, "
    "`top_5_positions`, `cash_pct`. Paper-trading accounts are excluded. Use these for the "
    "CONSERVATIVE lens's concentration critique — IPS only checks the per-trade delta, not "
    "the existing book, so cite `portfolio_context.sector_exposure_pct` and "
    "`portfolio_context.position_in_symbol.weight_pct` directly when pushing back on size."
)

_PROMPT_SLUG = "risk-neutral-v1-system-prompt"
_AGENT_SLUG = "risk-neutral-v1"


def _swap(old: str, new: str) -> None:
    conn = op.get_bind()
    conn.execute(
        text(
            "UPDATE prompts "
            "SET content = REPLACE(content, :old, :new), updated_at = NOW() "
            "WHERE slug = :slug AND position(:old in content) > 0"
        ),
        {"old": old, "new": new, "slug": _PROMPT_SLUG},
    )
    conn.execute(
        text(
            "UPDATE agents "
            "SET system_prompt = REPLACE(system_prompt, :old, :new) "
            "WHERE slug = :slug AND position(:old in system_prompt) > 0"
        ),
        {"old": old, "new": new, "slug": _AGENT_SLUG},
    )


def upgrade() -> None:
    _swap(_OLD_INPUTS, _NEW_INPUTS)


def downgrade() -> None:
    _swap(_NEW_INPUTS, _OLD_INPUTS)
