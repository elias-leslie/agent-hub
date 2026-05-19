"""enrich_portfolio_mgr_v1_portfolio_context

Revision ID: 8f56b94092a9
Revises: 26acec74f34e
Create Date: 2026-05-18

The PM now receives the household's portfolio_context. The final
decision's rationale must call out concentration changes the trade will
produce — IPS only checks the per-trade delta, but the PM is the audit
trail's last writer and needs to cite the post-trade book state.

Also updates the stale "three risk votes" reference now that the risk
stage produces one consolidated vote (see migration
``x9y0z1a2b3c4_consolidate_committee_risk_voters.py``).
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "8f56b94092a9"
down_revision: str | Sequence[str] | None = "26acec74f34e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_OLD_INPUTS = (
    "You are given:\n"
    "- The trader's proposed trade\n"
    "- The 3-round bull/bear debate transcript with scores\n"
    "- The three risk votes (aggressive, neutral, conservative)\n"
    "- The IPS check results\n"
    "- Past decisions on this symbol (last 5) with realized P/L\n"
    "- Any user feedback that triggered the run"
)
_NEW_INPUTS = (
    "You are given:\n"
    "- The trader's proposed trade\n"
    "- The 3-round bull/bear debate transcript with scores\n"
    "- The consolidated risk vote (one neutral voter that privately applies aggressive / "
    "conservative / neutral framings)\n"
    "- The IPS check results\n"
    "- Past decisions on this symbol (last 5) with realized P/L\n"
    "- `portfolio_context` for the household: `position_in_symbol` (shares, weight_pct, "
    "sector), `sector_exposure_pct` (combined weight of every holding in this symbol's "
    "sector), `top_5_positions`, `cash_pct`. Paper-trading accounts are excluded.\n"
    "- Any user feedback that triggered the run"
)

_OLD_PRINCIPLES = (
    "- If IPS reports `all_passed=false` and any check is severity=block, you MUST either "
    "(a) downgrade size to compliance or (b) hold. You cannot approve a non-compliant trade.\n"
    "- Weight risk votes: if median risk score ≤ -0.4, downgrade or hold even if the trader "
    "was confident."
)
_NEW_PRINCIPLES = (
    "- If IPS reports `all_passed=false` and any check is severity=block, you MUST either "
    "(a) downgrade size to compliance or (b) hold. You cannot approve a non-compliant trade.\n"
    "- Weight risk votes: if median risk score ≤ -0.4, downgrade or hold even if the trader "
    "was confident.\n"
    "- Portfolio-aware final sizing: cite `portfolio_context.position_in_symbol.weight_pct` "
    "and the post-trade weight you are approving; cite "
    "`portfolio_context.sector_exposure_pct` when the trade meaningfully shifts the "
    "sector concentration. IPS checks the per-trade delta only — the PM owns the book-wide read."
)

_PROMPT_SLUG = "portfolio-mgr-v1-system-prompt"
_AGENT_SLUG = "portfolio-mgr-v1"


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
