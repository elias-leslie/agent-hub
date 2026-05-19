"""enrich_trader_v1_portfolio_context

Revision ID: cd9d123a7fb3
Revises: dbce19a40000
Create Date: 2026-05-18

Portfolio-AI now passes the trader an explicit ``portfolio_context``
kwarg containing the household's position in the symbol, sector exposure,
top-5 holdings, cash %. The prior trader prompt knew only ``portfolio_value``
and ``current_price`` — when sizing it had no way to flag "we already own
8% in this name" or "tech sector is 28% before we add". This migration
appends a portfolio-aware sizing rule and updates the input list so the
trader's rationale must cite ``portfolio_context.position_in_symbol`` and
``portfolio_context.sector_exposure_pct`` when relevant.
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "cd9d123a7fb3"
down_revision: str | Sequence[str] | None = "dbce19a40000"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_OLD_INPUTS = (
    "You are given:\n"
    "- The four analyst reports (fundamentals, news, sentiment, technical)\n"
    "- The full 3-round bull/bear debate transcript with scores\n"
    "- The current quote and the user's portfolio value\n"
    "- Past decisions on this symbol (last 5) + their realized P/L"
)
_NEW_INPUTS = (
    "You are given:\n"
    "- The four analyst reports (fundamentals, news, sentiment, technical)\n"
    "- The full 3-round bull/bear debate transcript with scores\n"
    "- The current quote and the user's portfolio value\n"
    "- Past decisions on this symbol (last 5) + their realized P/L\n"
    "- `portfolio_context` for the household: `position_in_symbol` (shares, cost_basis, current_value, weight_pct, sector), `sector_exposure_pct` (combined weight of every holding in this symbol's sector), `sector_breakdown` (sector→weight_pct map), `top_5_positions` (largest live holdings), `cash_pct` (cash / total capital). Paper-trading accounts are excluded."
)

_OLD_PRINCIPLES = (
    "# Principles\n"
    "- Size proportionally to conviction. A `confidence ≈ 0.55` bull thesis sized at 0.05 "
    "(5%) is honest; sized at 0.25 it is reckless.\n"
    "- \"Hold\" is a valid action when the debate is genuinely balanced. Do not force a trade.\n"
    "- Past decisions + P/L: if a similar prior decision was wrong, explain what is different "
    "now. If you cannot, downgrade size.\n"
    "- Stops are not mandatory but if the technical analyst named a level, prefer that level.\n"
    "- Your rationale must reference specific debate moments and analyst claims, not platitudes."
)
_NEW_PRINCIPLES = (
    "# Principles\n"
    "- Size proportionally to conviction. A `confidence ≈ 0.55` bull thesis sized at 0.05 "
    "(5%) is honest; sized at 0.25 it is reckless.\n"
    "- \"Hold\" is a valid action when the debate is genuinely balanced. Do not force a trade.\n"
    "- Past decisions + P/L: if a similar prior decision was wrong, explain what is different "
    "now. If you cannot, downgrade size.\n"
    "- Stops are not mandatory but if the technical analyst named a level, prefer that level.\n"
    "- Your rationale must reference specific debate moments and analyst claims, not platitudes.\n"
    "- Portfolio-aware sizing: read `portfolio_context.position_in_symbol` first. If we "
    "already hold the name, a buy is an `add`, not a fresh `buy`; cite the existing "
    "`weight_pct` and the post-trade weight you are targeting. Cite "
    "`portfolio_context.sector_exposure_pct` when proposing meaningful size in a sector "
    "we are already heavy in (>20%) — either justify the concentration or downgrade. "
    "Cite `portfolio_context.cash_pct` when proposing a size larger than available cash "
    "would support."
)

_PROMPT_SLUG = "trader-v1-system-prompt"
_AGENT_SLUG = "trader-v1"


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
    _swap(_OLD_PRINCIPLES, _NEW_PRINCIPLES)


def downgrade() -> None:
    _swap(_NEW_PRINCIPLES, _OLD_PRINCIPLES)
    _swap(_NEW_INPUTS, _OLD_INPUTS)
