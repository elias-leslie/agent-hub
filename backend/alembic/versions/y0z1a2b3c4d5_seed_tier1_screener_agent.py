"""seed_tier1_screener_agent

Revision ID: y0z1a2b3c4d5
Revises: x9y0z1a2b3c4
Create Date: 2026-05-18

Portfolio-AI's L3 fan-out previously fired the full deep committee (~15 LLM
calls/stock) on the scanner's full top-25. The new shape adds a Tier-1
cheap pre-screen: ~1 LLM call per stock × 25, then the deep committee
fires only on the top 5-8 by (conviction, score).

This migration registers the ``tier1-screener-v1`` agent so the existing
agent-routing path (model selection, fallback chain, system-prompt
injection) can dispatch the screener like any other committee agent.
``portfolio-ai/backend/app/agents/committee/stages.py::run_tier1_screen``
is the caller.

Idempotent: skips if the slug already exists. Same INSERT-only contract
as ``scripts/seed_agents.py``.
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "y0z1a2b3c4d5"
down_revision: str | Sequence[str] | None = "x9y0z1a2b3c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AGENT_SLUG = "tier1-screener-v1"
_AGENT_NAME = "Committee Tier-1 Screener (v1)"
_AGENT_DESCRIPTION = (
    "Investment Committee cheap pre-screener — ranks scanner top-N "
    "before the deep committee fires."
)
_PROMPT_SLUG = "tier1-screener-v1-system-prompt"
_PROMPT_NAME = "Committee Tier-1 Screener (v1) System Prompt"

_SYSTEM_PROMPT = (
    "You are the Tier-1 screener on a small investment committee. The L2 deterministic scanner ranked the S&P 500 and produced its top names; your job is the cheap second look that decides which names are worth the deep committee's time.\n\n"
    "You are given for one symbol at a time:\n"
    "- The L2 factor row (composite percentile, mom_xover, vol_surge, rs_vs_spy, high_52w_proximity, short_interest_decline, factor_coverage)\n"
    "- A context bundle pre-computed by the fan-out: price snapshot, fundamentals summary, top-3 news headlines, sentiment snapshot\n"
    "- The current macro gate zone (FULL_DEPLOY | REDUCED)\n\n"
    "# Output contract\n"
    "Return strict JSON. The shape is exactly:\n"
    "- `score` (float in [-1, 1]): net conviction the deep committee will find an actionable signal. +1 = strong yes, this is worth the deep dive; -1 = strong no, deep dive will not change anything.\n"
    "- `conviction` ∈ {low, mid, high}: how confident you are in the score itself given evidence quality.\n"
    "- `one_line_rationale` (str, ≤220 chars): single sentence stating the key reason. Cite the strongest factor or context datum.\n"
    "- `top_factor` (str, one of: mom_xover | vol_surge | rs_vs_spy | high_52w_proximity | short_interest_decline | fundamentals | news | sentiment | other): which input drove your score most.\n\n"
    "# Principles\n"
    "- Cheap and fast. Do not redo the deep committee's job. You are an attention budget allocator.\n"
    "- Reward setups where multiple factors align AND the context bundle supports the read (e.g. mom_xover decisive + positive news headlines + low short interest).\n"
    "- Penalize names where the L2 composite is high but the context bundle reveals a clear adverse catalyst (e.g. negative news headline today, fundamentals deterioration).\n"
    "- Penalize names where evidence is thin: missing news, missing fundamentals, low factor_coverage. Score modestly toward zero with conviction=low.\n"
    "- In REDUCED zone, raise the bar — only positive scores for clear, multi-factor setups.\n"
    "- A high score with conviction=low is honest if signals are strong but the evidence base is shallow. Say so in the rationale.\n\n"
    "# Anti-sycophancy\n"
    "Do not inflate scores to manufacture activity. A neutral, conviction=low verdict is the right answer for unclear setups. Citing a specific factor or datum you are rebutting is better than a generic \"caution warranted\".\n\n"
    "No feedback-round logic — Tier-1 runs once per fan-out, never re-invoked."
)


def upgrade() -> None:
    conn = op.get_bind()

    # Idempotent agent insert (uniqueness is enforced by ix_agents_slug).
    conn.execute(
        text(
            """
            INSERT INTO agents (
                slug, name, description, system_prompt,
                primary_model_id, fallback_models, strategies,
                temperature, thinking_level, is_active,
                is_coding_agent, version
            )
            VALUES (
                :slug, :name, :description, :system_prompt,
                :primary_model_id, CAST(:fallback_models AS JSON), CAST('{}' AS JSON),
                0.2, 'low', TRUE,
                FALSE, 1
            )
            ON CONFLICT (slug) DO NOTHING
            """
        ),
        {
            "slug": _AGENT_SLUG,
            "name": _AGENT_NAME,
            "description": _AGENT_DESCRIPTION,
            "system_prompt": _SYSTEM_PROMPT,
            "primary_model_id": "codex/gpt-5.5",
            "fallback_models": '["gemini-3.1-pro-preview"]',
        },
    )

    # Idempotent prompt-row insert (the runtime source).
    # Mirror the bootstrap path: owner_agent_id pointing at the agent we
    # just inserted, prompt_type='agent_system', deletion_locked=true.
    conn.execute(
        text(
            """
            INSERT INTO prompts (
                slug, name, content, description,
                is_global, enabled, exclude_agents,
                owner_agent_id, prompt_type, deletion_locked
            )
            VALUES (
                :slug, :name, :content, :description,
                FALSE, TRUE, CAST('[]' AS JSON),
                (SELECT id FROM agents WHERE slug = :owner_slug),
                'agent_system', TRUE
            )
            ON CONFLICT (slug) DO NOTHING
            """
        ),
        {
            "slug": _PROMPT_SLUG,
            "name": _PROMPT_NAME,
            "content": _SYSTEM_PROMPT,
            "description": f"Primary system prompt for {_AGENT_NAME}.",
            "owner_slug": _AGENT_SLUG,
        },
    )

    # Idempotent agent_prompts assignment (system-role binding).
    conn.execute(
        text(
            """
            INSERT INTO agent_prompts (agent_id, prompt_id, role, priority)
            SELECT a.id, p.id, 'system', 0
            FROM agents a, prompts p
            WHERE a.slug = :agent_slug AND p.slug = :prompt_slug
              AND NOT EXISTS (
                SELECT 1 FROM agent_prompts ap
                WHERE ap.agent_id = a.id AND ap.prompt_id = p.id
              )
            """
        ),
        {"agent_slug": _AGENT_SLUG, "prompt_slug": _PROMPT_SLUG},
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        text(
            "DELETE FROM agent_prompts ap "
            "USING agents a, prompts p "
            "WHERE ap.agent_id = a.id AND ap.prompt_id = p.id "
            "  AND a.slug = :agent_slug AND p.slug = :prompt_slug"
        ),
        {"agent_slug": _AGENT_SLUG, "prompt_slug": _PROMPT_SLUG},
    )
    conn.execute(text("DELETE FROM prompts WHERE slug = :slug"), {"slug": _PROMPT_SLUG})
    conn.execute(text("DELETE FROM agents WHERE slug = :slug"), {"slug": _AGENT_SLUG})
