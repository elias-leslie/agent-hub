"""Upgrade game audio critic to Gemini 3.5 Flash.

Revision ID: f01de1c4adc1
Revises: e7f8a9b0c1d2
Create Date: 2026-07-15 20:44:37.679700

"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f01de1c4adc1"
down_revision: str | Sequence[str] | None = "e7f8a9b0c1d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


MODEL_ID = "gemini-3.5-flash"
PREVIOUS_MODEL_ID = "gemini-3-flash-preview"


INSERT_MODEL = sa.text(
    """
    INSERT INTO models (
        id, alias, name, hint, provider,
        score_coding, score_reasoning, score_planning, score_tool_use,
        score_instruction, score_design,
        cost_input_per_m, cost_output_per_m, pricing_unit, service_tiers,
        cache_read_per_million, context_window, speed_tier,
        can_generate_images, has_vision, can_edit_images, has_thinking,
        supports_pdf, supports_audio, supports_tool_execution,
        supports_verbosity, supports_xhigh, supports_session_cache,
        max_output_tokens, release_date, knowledge_cutoff, family,
        availability, is_active, sort_order, source
    ) VALUES (
        :id, '3.5-flash', 'Gemini 3.5 Flash', 'Frontier speed', 'gemini',
        85, 94, 84, 86, 90, 90,
        1.50, 9.00, 'per_million_tokens', CAST(:service_tiers AS jsonb),
        0.15, 1048576, 'fast',
        false, true, false, true,
        true, true, true,
        false, false, false,
        65536, '2026-05-19', '2025-01-01', 'gemini-flash',
        'stable; free_tier; quotas_project_specific_ai_studio',
        true, 4, 'seed'
    )
    ON CONFLICT (id) DO UPDATE SET
        alias = EXCLUDED.alias,
        name = EXCLUDED.name,
        hint = EXCLUDED.hint,
        provider = EXCLUDED.provider,
        score_coding = EXCLUDED.score_coding,
        score_reasoning = EXCLUDED.score_reasoning,
        score_planning = EXCLUDED.score_planning,
        score_tool_use = EXCLUDED.score_tool_use,
        score_instruction = EXCLUDED.score_instruction,
        score_design = EXCLUDED.score_design,
        cost_input_per_m = EXCLUDED.cost_input_per_m,
        cost_output_per_m = EXCLUDED.cost_output_per_m,
        service_tiers = EXCLUDED.service_tiers,
        cache_read_per_million = EXCLUDED.cache_read_per_million,
        context_window = EXCLUDED.context_window,
        speed_tier = EXCLUDED.speed_tier,
        has_vision = EXCLUDED.has_vision,
        has_thinking = EXCLUDED.has_thinking,
        supports_pdf = EXCLUDED.supports_pdf,
        supports_audio = EXCLUDED.supports_audio,
        supports_tool_execution = EXCLUDED.supports_tool_execution,
        max_output_tokens = EXCLUDED.max_output_tokens,
        release_date = EXCLUDED.release_date,
        knowledge_cutoff = EXCLUDED.knowledge_cutoff,
        family = EXCLUDED.family,
        availability = EXCLUDED.availability,
        is_active = true,
        source = EXCLUDED.source,
        updated_at = now()
    """
)


def upgrade() -> None:
    """Register Gemini 3.5 Flash and route the audio critic to it."""

    bind = op.get_bind()
    bind.execute(
        INSERT_MODEL,
        {
            "id": MODEL_ID,
            "service_tiers": json.dumps(
                {"default": 1.0, "batch": 0.5, "flex": 0.5, "priority": 1.8}
            ),
        },
    )
    bind.execute(
        sa.text(
            """
            UPDATE agents
            SET primary_model_id = :model_id,
                version = version + 1,
                updated_at = now()
            WHERE slug = 'game-audio-critic'
              AND primary_model_id <> :model_id
            """
        ),
        {"model_id": MODEL_ID},
    )


def downgrade() -> None:
    """Restore the audio critic route and remove the stable model row."""

    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE agents
            SET primary_model_id = :previous_model_id,
                version = version + 1,
                updated_at = now()
            WHERE slug = 'game-audio-critic'
              AND primary_model_id = :model_id
            """
        ),
        {"model_id": MODEL_ID, "previous_model_id": PREVIOUS_MODEL_ID},
    )
    bind.execute(sa.text("DELETE FROM models WHERE id = :model_id"), {"model_id": MODEL_ID})
