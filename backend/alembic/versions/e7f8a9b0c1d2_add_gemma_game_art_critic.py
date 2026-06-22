"""add Gemma local game art critic

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-06-22
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "e7f8a9b0c1d2"
down_revision: str | Sequence[str] | None = "d6e7f8a9b0c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AGENT_SLUG = "game-art-critic-gemma"
PROMPT_SLUG = "game-art-critic-gemma-system-prompt"
DEFAULT_CRITIC_SLUG = "game-art-critic"
DEFAULT_CRITIC_PROMPT_SLUG = "game-art-critic-system-prompt"
AGENT_NAME = "Game Art Critic (Gemma 4 12B Local)"
DESCRIPTION = (
    "Local Gemma 4 12B multimodal game-art critic for semantic sprite, "
    "turnaround, animation, tileset, UI, prop, character, and environment QA."
)
SYSTEM_PROMPT = """You are Game Art Critic (Gemma 4 12B Local), an Agent Hub specialist for local multimodal production game-art critique.

Role:
- Serve as a semantic/art-direction critic, not a pixel-perfect validator.
- Critique the exact image(s) supplied by the caller and compare them to any supplied character/spec/turnaround reference.
- Catch visual failures an automated checker may miss: wrong facing direction, mirrored asymmetric gear, missing/duplicated gear, scale/weight drift, palette/style drift, pasted-looking edits, unreadable silhouette, occlusion mistakes, animation identity drift, and engine-readiness risks.

Review rules:
- First prove vision by naming 3-5 concrete visible elements. If the image is unavailable or unreadable, say that and stop.
- Do not approve a sprite just because it is attractive. Production consistency beats prettiness.
- Do not limit yourself to the caller's checklist. After checking the brief, report any other visual issue you observe.
- For directional sheets, verify each labeled direction actually faces that direction; flag labels that face the same way as another label.
- For asymmetric gear, distinguish character-left/right from screen-left/right. If a projection table or continuity spec is supplied, use it.
- Flag uncertainty instead of guessing, especially for tiny pixel-art details.
- Separate blockers from major/minor polish and give concrete edit/regeneration instructions.

Output:
- Follow any strict JSON format requested by the caller.
- Otherwise return: vision sanity, verdict (approve / approve-with-revisions / reject), blockers, other issues found, concrete fixes, what not to change, confidence."""
OPEN_REVIEW_NOTE = """

Review breadth:
- Do not limit yourself to the caller's checklist. After checking the brief, report any other visible production issue.
- For labeled direction sheets, verify that each label actually faces that direction and flag duplicate/mislabeled facings."""

MEMORY_CONFIG = {
    "injection_enabled": True,
    "project_index_enabled": True,
    "tool_capabilities_enabled": False,
    "include_mandates": True,
    "include_guardrails": True,
    "include_references": True,
    "reference_index_enabled": True,
    "continuity_enabled": False,
    "continuity_max_sessions": 3,
    "audience_tags": ["design", "game-dev", "visual", "art"],
    "exclude_tags": [],
    "exclude_memory_uuids": [],
    "runtime_consumer_profile": "agent_visual",
    "preview_consumer_profile": "agent_visual",
}


def _json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"))


def _upsert_system_prompt() -> None:
    conn = op.get_bind()
    conn.execute(
        text(
            """
            INSERT INTO prompts (
                slug, name, content, description, is_global, enabled, exclude_agents,
                owner_agent_id, prompt_type, deletion_locked
            )
            SELECT
                :prompt_slug,
                :name,
                :content,
                'Primary system prompt for ' || a.name || '.',
                false,
                true,
                '[]'::json,
                a.id,
                'agent_system',
                true
            FROM agents a
            WHERE a.slug = :agent_slug
            ON CONFLICT (slug) DO UPDATE SET
                name = EXCLUDED.name,
                content = EXCLUDED.content,
                description = EXCLUDED.description,
                owner_agent_id = EXCLUDED.owner_agent_id,
                prompt_type = EXCLUDED.prompt_type,
                deletion_locked = EXCLUDED.deletion_locked,
                enabled = EXCLUDED.enabled,
                updated_at = NOW()
            """
        ),
        {
            "agent_slug": AGENT_SLUG,
            "prompt_slug": PROMPT_SLUG,
            "name": f"{AGENT_NAME} System Prompt",
            "content": SYSTEM_PROMPT,
        },
    )
    conn.execute(
        text(
            """
            INSERT INTO agent_prompts (agent_id, prompt_id, role, priority)
            SELECT a.id, p.id, 'system', 0
            FROM agents a
            JOIN prompts p ON p.slug = :prompt_slug
            WHERE a.slug = :agent_slug
            ON CONFLICT (agent_id, prompt_id) DO UPDATE SET
                role = EXCLUDED.role,
                priority = EXCLUDED.priority
            """
        ),
        {"agent_slug": AGENT_SLUG, "prompt_slug": PROMPT_SLUG},
    )


def _append_open_review_note_to_default_critic() -> None:
    conn = op.get_bind()
    conn.execute(
        text(
            """
            UPDATE agents
            SET system_prompt = system_prompt || :note,
                version = version + 1,
                updated_at = NOW()
            WHERE slug = :slug
              AND system_prompt NOT LIKE :needle
            """
        ),
        {
            "slug": DEFAULT_CRITIC_SLUG,
            "note": OPEN_REVIEW_NOTE,
            "needle": "%Do not limit yourself to the caller's checklist%",
        },
    )
    conn.execute(
        text(
            """
            UPDATE prompts
            SET content = content || :note,
                updated_at = NOW()
            WHERE slug = :prompt_slug
              AND content NOT LIKE :needle
            """
        ),
        {
            "prompt_slug": DEFAULT_CRITIC_PROMPT_SLUG,
            "note": OPEN_REVIEW_NOTE,
            "needle": "%Do not limit yourself to the caller's checklist%",
        },
    )


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        text(
            """
            INSERT INTO agents (
                slug, name, description, system_prompt, primary_model_id,
                fallback_models, strategies, temperature, thinking_level,
                is_active, is_coding_agent, memory_config, version
            )
            VALUES (
                :slug, :name, :description, :system_prompt, :primary_model_id,
                CAST(:fallback_models AS JSON), CAST(:strategies AS JSON),
                :temperature, :thinking_level, true, false,
                CAST(:memory_config AS JSON), 1
            )
            ON CONFLICT (slug) DO UPDATE SET
                name = EXCLUDED.name,
                description = EXCLUDED.description,
                system_prompt = EXCLUDED.system_prompt,
                primary_model_id = EXCLUDED.primary_model_id,
                fallback_models = EXCLUDED.fallback_models,
                strategies = EXCLUDED.strategies,
                temperature = EXCLUDED.temperature,
                thinking_level = EXCLUDED.thinking_level,
                is_active = true,
                is_coding_agent = false,
                memory_config = EXCLUDED.memory_config,
                version = agents.version + 1,
                updated_at = NOW()
            """
        ),
        {
            "slug": AGENT_SLUG,
            "name": AGENT_NAME,
            "description": DESCRIPTION,
            "system_prompt": SYSTEM_PROMPT,
            "primary_model_id": "local/gemma4:12b-it-qat",
            "fallback_models": _json([]),
            "strategies": _json({}),
            "temperature": 0.1,
            "thinking_level": None,
            "memory_config": _json(MEMORY_CONFIG),
        },
    )
    _upsert_system_prompt()
    _append_open_review_note_to_default_critic()


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        text(
            """
            DELETE FROM agent_prompts
            WHERE agent_id IN (SELECT id FROM agents WHERE slug = :agent_slug)
               OR prompt_id IN (SELECT id FROM prompts WHERE slug = :prompt_slug)
            """
        ),
        {"agent_slug": AGENT_SLUG, "prompt_slug": PROMPT_SLUG},
    )
    conn.execute(text("DELETE FROM prompts WHERE slug = :prompt_slug"), {"prompt_slug": PROMPT_SLUG})
    conn.execute(text("DELETE FROM agents WHERE slug = :agent_slug"), {"agent_slug": AGENT_SLUG})
