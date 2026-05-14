"""update_gemini_catalog

Revision ID: r4s5t6u7v8w9
Revises: q3r4s5t6u7v8
Create Date: 2026-05-14 12:00:00.000000
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "r4s5t6u7v8w9"
down_revision: str | Sequence[str] | None = "q3r4s5t6u7v8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


GEMINI_ROWS = [
    {
        "id": "gemini-3-flash-preview",
        "alias": "flash",
        "name": "Gemini 3 Flash Preview",
        "hint": "Fast",
        "score_coding": 78,
        "score_reasoning": 90,
        "score_planning": 72,
        "score_tool_use": 75,
        "score_instruction": 83,
        "score_design": 85,
        "cost_input_per_m": 0.50,
        "cost_output_per_m": 3.00,
        "cache_read_per_million": 0.05,
        "release_date": "2025-12-11",
        "knowledge_cutoff": "2025-09-01",
        "family": "gemini-flash",
        "availability": "free_tier; quotas_project_specific_ai_studio",
        "speed_tier": "fast",
        "sort_order": 4,
    },
    {
        "id": "gemini-3.1-flash-lite",
        "alias": "3.1-flash-lite",
        "name": "Gemini 3.1 Flash-Lite",
        "hint": "High throughput",
        "score_coding": 56,
        "score_reasoning": 64,
        "score_planning": 46,
        "score_tool_use": 49,
        "score_instruction": 86,
        "score_design": 58,
        "cost_input_per_m": 0.25,
        "cost_output_per_m": 1.50,
        "cache_read_per_million": 0.025,
        "release_date": "2026-05-01",
        "knowledge_cutoff": "2025-01-01",
        "family": "gemini-flash-lite",
        "availability": "free_tier; quotas_project_specific_ai_studio",
        "speed_tier": "fast",
        "sort_order": 5,
    },
    {
        "id": "gemini-3.1-flash-lite-preview",
        "alias": "3.1-flash-lite-preview",
        "name": "Gemini 3.1 Flash-Lite Preview",
        "hint": "Agentic cheap",
        "score_coding": 58,
        "score_reasoning": 66,
        "score_planning": 48,
        "score_tool_use": 51,
        "score_instruction": 86,
        "score_design": 58,
        "cost_input_per_m": 0.25,
        "cost_output_per_m": 1.50,
        "cache_read_per_million": 0.025,
        "release_date": "2026-03-03",
        "knowledge_cutoff": "2025-01-01",
        "family": "gemini-flash-lite",
        "availability": "free_tier_preview; quotas_project_specific_ai_studio",
        "speed_tier": "fast",
        "sort_order": 6,
    },
    {
        "id": "gemini-2.5-flash",
        "alias": "2.5-flash",
        "name": "Gemini 2.5 Flash",
        "hint": "Price performance",
        "score_coding": 72,
        "score_reasoning": 84,
        "score_planning": 68,
        "score_tool_use": 70,
        "score_instruction": 84,
        "score_design": 78,
        "cost_input_per_m": 0.30,
        "cost_output_per_m": 2.50,
        "cache_read_per_million": 0.03,
        "release_date": "2025-03-20",
        "knowledge_cutoff": "2025-01-01",
        "family": "gemini-flash",
        "availability": "free_tier; quotas_project_specific_ai_studio",
        "speed_tier": "fast",
        "sort_order": 7,
    },
    {
        "id": "gemini-2.5-flash-lite",
        "alias": "flash-lite",
        "name": "Gemini 2.5 Flash-Lite",
        "hint": "Cheap",
        "score_coding": 34,
        "score_reasoning": 50,
        "score_planning": 40,
        "score_tool_use": 45,
        "score_instruction": 84,
        "score_design": 55,
        "cost_input_per_m": 0.10,
        "cost_output_per_m": 0.40,
        "cache_read_per_million": 0.01,
        "release_date": "2025-06-01",
        "knowledge_cutoff": "2025-01-01",
        "family": "gemini-flash-lite",
        "availability": "free_tier; quotas_project_specific_ai_studio",
        "speed_tier": "fast",
        "sort_order": 8,
    },
    {
        "id": "gemini-3.1-pro-preview",
        "alias": "3.1-pro",
        "name": "Gemini 3.1 Pro Preview",
        "hint": "Deep reasoning",
        "score_coding": 82,
        "score_reasoning": 96,
        "score_planning": 82,
        "score_tool_use": 82,
        "score_instruction": 88,
        "score_design": 90,
        "cost_input_per_m": 2.00,
        "cost_output_per_m": 12.00,
        "cache_read_per_million": 0.20,
        "release_date": "2026-02-01",
        "knowledge_cutoff": "2025-11-01",
        "family": "gemini-pro",
        "availability": "paid_only; context_over_200k_costs_more",
        "speed_tier": "slow",
        "sort_order": 9,
    },
    {
        "id": "gemini-2.5-pro",
        "alias": "2.5-pro",
        "name": "Gemini 2.5 Pro",
        "hint": "Deep reasoning",
        "score_coding": 80,
        "score_reasoning": 92,
        "score_planning": 78,
        "score_tool_use": 80,
        "score_instruction": 86,
        "score_design": 82,
        "cost_input_per_m": 1.25,
        "cost_output_per_m": 10.00,
        "cache_read_per_million": 0.125,
        "release_date": "2025-03-20",
        "knowledge_cutoff": "2025-01-01",
        "family": "gemini-pro",
        "availability": "free_tier; context_over_200k_costs_more; quotas_project_specific_ai_studio",
        "speed_tier": "medium",
        "sort_order": 10,
    },
]


UPSERT_SQL = sa.text(
    """
    INSERT INTO models (
        id, alias, name, hint, provider,
        score_coding, score_reasoning, score_planning, score_tool_use, score_instruction, score_design,
        cost_input_per_m, cost_output_per_m, pricing_unit, unit_price, service_tiers,
        cache_read_per_million, cache_write_per_million,
        context_window, speed_tier,
        can_generate_images, has_vision, can_edit_images, has_thinking,
        supports_pdf, supports_audio, supports_tool_execution, supports_verbosity,
        supports_xhigh, supports_session_cache, max_output_tokens,
        release_date, knowledge_cutoff, family, availability,
        is_active, sort_order, source
    )
    VALUES (
        :id, :alias, :name, :hint, 'gemini',
        :score_coding, :score_reasoning, :score_planning, :score_tool_use, :score_instruction, :score_design,
        :cost_input_per_m, :cost_output_per_m, 'per_million_tokens', NULL, CAST(:service_tiers AS jsonb),
        :cache_read_per_million, NULL,
        1000000, :speed_tier,
        false, true, false, true,
        true, true, true, false,
        false, false, 65536,
        :release_date, :knowledge_cutoff, :family, :availability,
        true, :sort_order, 'seed'
    )
    ON CONFLICT (id) DO UPDATE SET
        alias = EXCLUDED.alias,
        name = EXCLUDED.name,
        hint = EXCLUDED.hint,
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
        is_active = EXCLUDED.is_active,
        sort_order = EXCLUDED.sort_order,
        updated_at = NOW()
    """
)


def upgrade() -> None:
    conn = op.get_bind()
    service_tiers = json.dumps({"default": 1.0, "batch": 0.5, "flex": 0.5, "priority": 1.8})
    for row in GEMINI_ROWS:
        conn.execute(UPSERT_SQL, {**row, "service_tiers": service_tiers})
        conn.execute(
            sa.text(
                """
                INSERT INTO model_aliases (alias, model_id, alias_type, source)
                VALUES (:alias, :model_id, 'canonical', 'seed')
                ON CONFLICT (alias) DO UPDATE SET
                    model_id = EXCLUDED.model_id,
                    alias_type = EXCLUDED.alias_type,
                    source = EXCLUDED.source,
                    updated_at = NOW()
                """
            ),
            {"alias": row["alias"], "model_id": row["id"]},
        )

    conn.execute(
        sa.text(
            """
            UPDATE models
            SET sort_order = CASE id
                WHEN 'gemini-3-pro-image-preview' THEN 11
                WHEN 'gemini-2.5-flash-image' THEN 12
                WHEN 'gemini-3.1-flash-image-preview' THEN 13
                ELSE sort_order
            END,
            updated_at = NOW()
            WHERE id IN (
                'gemini-3-pro-image-preview',
                'gemini-2.5-flash-image',
                'gemini-3.1-flash-image-preview'
            )
            """
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            DELETE FROM model_aliases
            WHERE alias IN ('3.1-flash-lite-preview', '2.5-flash', '2.5-pro')
            """
        )
    )
    conn.execute(
        sa.text(
            """
            DELETE FROM models
            WHERE id IN (
                'gemini-3.1-flash-lite-preview',
                'gemini-2.5-flash',
                'gemini-2.5-pro'
            )
            """
        )
    )
