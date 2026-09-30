"""Register GPT-6.1 Sol and promote qualified general-purpose routes.

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2

Official specs: https://developers.openai.com/api/docs/models/gpt-6.1-sol
Checked 2026-09-30. No release date or benchmark score is inferred. Required
house score columns inherit GPT-5.5 values until measured task evidence replaces
them. The metered route uses Chat Completions, so it cannot advertise tool calls;
the Codex OAuth route uses Responses and supports them.

OAuth qualification before promotion: Agent Hub session
d8910f67-8bd8-474b-840f-4750e48ee3bf served codex/gpt-6.1-sol with provider=codex,
fallback_used=false, finish_reason=stop, 2676 input and 15 output tokens.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "c8d9e0f1a2b3"
down_revision: str | Sequence[str] | None = "b7c8d9e0f1a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MODEL_ID = "codex/gpt-6.1-sol"
_CODING_FALLBACKS = [
    "kimi-code/kimi-for-coding", "moonshot/kimi-k2.6", "deepseek/deepseek-v4-pro",
    "minimax/MiniMax-M3", "nvidia/glm-5.2", "gemini-3.7-flash",
    "cloudflare/gpt-oss-120b", "local/gemma4:12b-it-qat",
]
_GENERAL_FALLBACKS = [
    "nvidia/minimax-m3", "gemini-3.7-flash", "deepseek/deepseek-v4-pro",
    "minimax/MiniMax-M3", "cloudflare/kimi-k2.6", "local/gemma4:12b-it-qat",
]
# slug: (exact previous model, effort, fallbacks, escalation, new effort)
_ROUTES = {
    "coder": ("codex/gpt-5.5", "xhigh", _CODING_FALLBACKS, None, "medium"),
    "debugger": ("codex/gpt-5.5", "xhigh", _CODING_FALLBACKS, None, "high"),
    "designer": ("codex/gpt-5.5", "high", _GENERAL_FALLBACKS, None, "medium"),
    "fixer": ("codex/gpt-5.5", "medium", ["codex/gpt-5.4", "claude-sonnet-4-6", "claude-opus-4-7", "gemini-3.1-flash-lite-preview"], None, "medium"),
    "optimizer": ("codex/gpt-5.5", "xhigh", _CODING_FALLBACKS, None, "high"),
    "refactor": ("codex/gpt-5.5", "low", _CODING_FALLBACKS, "codex/gpt-5.5", "medium"),
    "test-writer": ("codex/gpt-5.5", "high", _CODING_FALLBACKS, None, "medium"),
    "verifier": ("codex/gpt-5.5", "xhigh", _GENERAL_FALLBACKS, None, "high"),
    "ui-mockup-designer": ("codex/gpt-5.5", "high", _GENERAL_FALLBACKS, None, "medium"),
    "ux-polisher": ("codex/gpt-5.5", "high", _CODING_FALLBACKS, None, "medium"),
    "researcher": ("gemini-3.1-flash-lite", "high", ["minimax/MiniMax-M2.7", "cloudflare/glm-4.7-flash", "nvidia/minimax-m3", "local/gemma4:12b-it-qat"], None, "medium"),
    "neri-orchestrator": ("codex/gpt-6-astra", "xhigh", [], None, "medium"),
    "neri-reporter": ("codex/gpt-6-astra", "high", [], None, "medium"),
    "neri-reviewer": ("codex/gpt-6-astra", "high", [], None, "high"),
}
_REPORTER_DIGEST = "eda596549bee5bb54b3563a1fc87d1a840f586d774b5234af1bd17e99cb36283"
_REVIEWER_DIGEST = "25502db53b2e7e6682d774903cca343e61d4e1c3cd38e941ac9489121f6cdac9"
_OLD_IDENTITY = "record gpt-6-astra as the executing model."
_NEW_IDENTITY = "record gpt-6.1-sol as the executing model."


def _catalog_rows() -> list[dict[str, object]]:
    return [
        {
            "id": "openai/gpt-6.1-sol", "provider": "openai", "alias": "gpt-6.1-sol",
            "input_cost": 2.0, "output_cost": 10.0, "cache_read": 0.1,
            "cache_write": 2.5, "tiers": json.dumps({"default": 1.0, "flex": 0.5, "priority": 2.0}),
            "tools": False, "session_cache": False,
            "availability": "chat_completions_without_tools; input_over_272k_bills_2x_input_1.5x_output; fast_unavailable_with_eu_residency",
        },
        {
            "id": _MODEL_ID, "provider": "codex", "alias": "codex-gpt-6.1-sol",
            "input_cost": 0.0, "output_cost": 0.0, "cache_read": None,
            "cache_write": None, "tiers": json.dumps({"default": 1.0}),
            "tools": True, "session_cache": True,
            "availability": "codex_oauth_subscription; verified_2026-09-30; reasoning_low_medium_high_xhigh_max",
        },
    ]


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _reviewer_prompt(current: str, *, reverse: bool = False) -> str:
    previous = current.replace(_NEW_IDENTITY, _OLD_IDENTITY)
    if _digest(previous) != _REVIEWER_DIGEST or previous.count(_OLD_IDENTITY) != 1:
        raise RuntimeError("Neri reviewer prompt has an unknown model-migration revision")
    return previous if reverse else previous.replace(_OLD_IDENTITY, _NEW_IDENTITY)


def _check_route(slug: str, current) -> None:
    old_model, old_effort, old_fallbacks, old_escalation, effort = _ROUTES[slug]
    actual = (
        current["primary_model_id"], current["thinking_level"],
        current["fallback_models"] or [], current["escalation_model_id"],
    )
    if actual not in ((old_model, old_effort, old_fallbacks, old_escalation), (_MODEL_ID, effort, [], None)):
        raise RuntimeError(f"Agent '{slug}' has an unknown model-migration revision")


def _set_routes(conn, *, reverse: bool = False) -> None:
    for slug, (old_model, old_effort, old_fallbacks, old_escalation, effort) in _ROUTES.items():
        current = conn.execute(
            text("SELECT primary_model_id, thinking_level, fallback_models, escalation_model_id, system_prompt FROM agents WHERE slug = :slug FOR UPDATE"),
            {"slug": slug},
        ).mappings().one()
        _check_route(slug, current)
        prompt = current["system_prompt"]
        if slug == "neri-reporter" and _digest(prompt) != _REPORTER_DIGEST:
            raise RuntimeError("Neri reporter prompt has an unknown model-migration revision")
        if slug == "neri-reviewer":
            prompt = _reviewer_prompt(prompt, reverse=reverse)
        conn.execute(
            text("UPDATE agents SET primary_model_id = :model, thinking_level = :effort, fallback_models = CAST(:fallbacks AS JSON), escalation_model_id = :escalation, system_prompt = :prompt, version = version + 1, updated_at = NOW() WHERE slug = :slug"),
            {
                "slug": slug, "model": old_model if reverse else _MODEL_ID,
                "effort": old_effort if reverse else effort,
                "fallbacks": json.dumps(old_fallbacks if reverse else []),
                "escalation": old_escalation if reverse else None, "prompt": prompt,
            },
        )
        if slug == "neri-reviewer":
            conn.execute(
                text("UPDATE prompts SET content = :prompt, updated_at = NOW() WHERE slug = 'neri-reviewer-system-prompt'"),
                {"prompt": prompt},
            )


def upgrade() -> None:
    conn = op.get_bind()
    for row in _catalog_rows():
        result = conn.execute(
            text("""
                INSERT INTO models (
                    id, alias, name, hint, provider, score_coding, score_reasoning,
                    score_planning, score_tool_use, score_instruction, score_design,
                    cost_input_per_m, cost_output_per_m, service_tiers,
                    cache_read_per_million, cache_write_per_million, context_window,
                    speed_tier, has_vision, has_thinking, supports_tool_execution,
                    supports_xhigh, supports_session_cache, max_output_tokens,
                    knowledge_cutoff, family, availability, is_active, sort_order, source
                ) SELECT :id, :alias, 'GPT-6.1 Sol', 'General complex work', :provider,
                    score_coding, score_reasoning, score_planning, score_tool_use,
                    score_instruction, score_design, :input_cost, :output_cost,
                    CAST(:tiers AS JSONB), :cache_read, :cache_write, 1050000,
                    speed_tier, TRUE, TRUE, :tools, TRUE, :session_cache, 128000,
                    '2026-04-30', 'gpt', :availability, TRUE, sort_order, 'seed'
                FROM models WHERE id = :previous
                ON CONFLICT (id) DO UPDATE SET is_active = TRUE, updated_at = NOW()
                WHERE models.alias = EXCLUDED.alias
                  AND models.provider = EXCLUDED.provider
                  AND models.cost_input_per_m = EXCLUDED.cost_input_per_m
                  AND models.cost_output_per_m = EXCLUDED.cost_output_per_m
                  AND models.cache_read_per_million IS NOT DISTINCT FROM EXCLUDED.cache_read_per_million
                  AND models.cache_write_per_million IS NOT DISTINCT FROM EXCLUDED.cache_write_per_million
                  AND models.service_tiers = EXCLUDED.service_tiers
                  AND models.context_window = EXCLUDED.context_window
                  AND models.max_output_tokens = EXCLUDED.max_output_tokens
                  AND models.supports_tool_execution = EXCLUDED.supports_tool_execution
                  AND models.supports_session_cache = EXCLUDED.supports_session_cache
                  AND models.knowledge_cutoff = EXCLUDED.knowledge_cutoff
                  AND models.release_date IS NULL
                  AND models.availability = EXCLUDED.availability
            """),
            {**row, "previous": f"{row['provider']}/gpt-5.5"},
        )
        if result.rowcount != 1:
            raise RuntimeError("GPT-6.1 Sol catalog preimage is missing or already changed")
        alias_result = conn.execute(
            text("INSERT INTO model_aliases (alias, model_id, alias_type, source) VALUES (:alias, :id, 'canonical', 'seed') ON CONFLICT (alias) DO UPDATE SET model_id = EXCLUDED.model_id WHERE model_aliases.model_id = EXCLUDED.model_id"),
            {"alias": row["alias"], "id": row["id"]},
        )
        if alias_result.rowcount != 1:
            raise RuntimeError("GPT-6.1 Sol alias has an unknown pre-migration revision")
    _set_routes(conn)


def downgrade() -> None:
    conn = op.get_bind()
    _set_routes(conn, reverse=True)
    # Preserve catalog identity and historical receipts rather than deleting rows.
    conn.execute(
        text("UPDATE models SET is_active = FALSE, updated_at = NOW() WHERE id IN ('openai/gpt-6.1-sol', 'codex/gpt-6.1-sol')")
    )
