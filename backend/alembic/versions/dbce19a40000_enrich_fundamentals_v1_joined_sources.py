"""enrich_fundamentals_v1_joined_sources

Revision ID: dbce19a40000
Revises: 1bca3579d044
Create Date: 2026-05-18

Portfolio-AI's ``fetch_fundamental_snapshot`` now hands the analyst a
joined dict under ``context_slice.fundamentals_raw`` keyed by the source
table — ``valuation``, ``cash_flow``, ``health``, ``earnings_surprise_history``,
``watchlist``. The prior system prompt only cited the watchlist pillar
score (``fundamentals_raw.fundamental_score``); without explicit name
references to the joined sources, the LLM ignores P/E, FCF, F-score,
and the EPS-surprise history that the prompt's "business + valuation"
deliverable needs.

This migration replaces the grounding paragraph and the rules line so
the analyst is told to cite the specific paths into the new structure.
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "dbce19a40000"
down_revision: str | Sequence[str] | None = "1bca3579d044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_OLD_GROUND = (
    "Use only user payload `context_slice`. Required evidence sources: `fundamentals`, "
    "`valuation`, `fundamentals_raw`, `portfolio`. Ground each claim in payload path + value, "
    "e.g. `context_slice.fundamentals_raw.fundamental_score=66`, "
    "`context_slice.portfolio.position.weight_pct=3.2`. Missing field = cite it. "
    "Lower score magnitude. No memory, web, invented numbers."
)
_NEW_GROUND = (
    "Use only user payload `context_slice`. Required evidence sources: `fundamentals`, "
    "`valuation`, `fundamentals_raw`, `portfolio`. Ground each claim in payload path + value, "
    "e.g. `context_slice.fundamentals_raw.valuation.pe_ratio_trailing=46.08`, "
    "`context_slice.fundamentals_raw.cash_flow.free_cash_flow=96_676_000_000`, "
    "`context_slice.fundamentals_raw.cash_flow.fcf_yield=0.0177`, "
    "`context_slice.fundamentals_raw.health.f_score=4`, "
    "`context_slice.fundamentals_raw.health.z_score_zone='safe'`, "
    "`context_slice.fundamentals_raw.earnings_surprise_history[0].surprise_pct=15.6`, "
    "`context_slice.fundamentals_raw.watchlist.fundamental_score=66`, "
    "`context_slice.portfolio.position.weight_pct=3.2`. Missing field = cite it (e.g. "
    "\"`fundamentals_raw.valuation` absent — schema gap, lowering magnitude\"). "
    "Lower score magnitude. No memory, web, invented numbers."
)

_PROMPT_SLUG = "fundamentals-v1-system-prompt"
_AGENT_SLUG = "fundamentals-v1"


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
    _swap(_OLD_GROUND, _NEW_GROUND)


def downgrade() -> None:
    _swap(_NEW_GROUND, _OLD_GROUND)
