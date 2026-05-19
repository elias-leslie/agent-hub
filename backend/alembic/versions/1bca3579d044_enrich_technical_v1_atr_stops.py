"""enrich_technical_v1_atr_stops

Revision ID: 1bca3579d044
Revises: y0z1a2b3c4d5
Create Date: 2026-05-18

Portfolio-AI now hands the technical analyst a fully-hydrated
``context_slice.indicators_raw`` dict containing every column from the
``technical_indicators`` table — including ``atr_14``, which the trader
needs for ATR-based stop sizing. The previous system prompt only cited
``rsi_14`` and ``price_vs_sma_200_pct`` by name; without an explicit
reference to ``atr_14``, the LLM treats it as undifferentiated noise and
the trader's "stops follow the technical analyst" clause has nothing to
anchor on.

This migration appends a single rules line that names ``atr_14``
explicitly so the analyst's stop-sizing comment lands in the deliverable.
``agents.system_prompt`` is mirrored so the bootstrap path stays in sync
with ``prompts.content``.

Safety: UPDATE conditioned on the prior text being intact (rtrim'd to
dodge trailing-newline drift between the two storage paths).
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "1bca3579d044"
down_revision: str | Sequence[str] | None = "y0z1a2b3c4d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_OLD_RULES = (
    "Rules: cite bar dates and indicator values. Split primary trend from short noise. "
    "Include counter-evidence. Include portfolio held/weight when sizing risk changes. "
    "Conflicting indicators mean low-magnitude mixed read."
)
_NEW_RULES = (
    "Rules: cite bar dates and indicator values. Split primary trend from short noise. "
    "Include counter-evidence. Include portfolio held/weight when sizing risk changes. "
    "Conflicting indicators mean low-magnitude mixed read. "
    "When the regime calls for a stop, cite `context_slice.indicators_raw.atr_14` and "
    "recommend a stop level expressed as N\u00d7ATR below/above the latest close so the "
    "trader inherits a concrete number."
)

_PROMPT_SLUG = "technical-v1-system-prompt"
_AGENT_SLUG = "technical-v1"


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
    _swap(_OLD_RULES, _NEW_RULES)


def downgrade() -> None:
    _swap(_NEW_RULES, _OLD_RULES)
