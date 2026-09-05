"""Add the GPT-5.6 family (Sol, Terra, Luna) and GPT-6 Astra to the catalog.

Nothing 5.6-class existed here: the newest GPT row was gpt-5.5 (2026-04-23), and
the 06:00 catalog sync on 2026-09-04 succeeded without discovering any of these.
All 89 pre-existing rows are source='seed', and ``seed_model_catalog()`` never
overwrites an existing row, so a migration is the way new entries arrive.

Both tracks get rows, matching how 5.4 and 5.5 are already carried:

  * ``openai/*`` is the metered API route. Real published prices.
  * ``codex/*`` is the ChatGPT OAuth subscription route, priced 0/0 because it
    does not bill per token, with availability='codex_oauth_subscription'.

The subscription route was verified, not assumed. One minimal request per model
id against https://chatgpt.com/backend-api/codex/responses on 2026-09-04, with
codex/gpt-5.5 as a known-good control:

    gpt-5.5        http=200  served 'ok'
    gpt-5.6-sol    http=200  served 'ok'
    gpt-5.6-terra  http=200  served 'ok'
    gpt-5.6-luna   http=200  served 'ok'
    gpt-6-astra    http=200  served 'ok'
    gpt-5.6        http=400  {"detail":"The 'gpt-5.6' model is not supported
                              when using Codex with a ChatGPT account."}

So the documented ``gpt-5.6`` alias for Sol is deliberately NOT registered: it
resolves on the metered API but is rejected on the route this deployment
actually authenticates through, and a catalog row that 400s is worse than no
row. The three concrete 5.6 snapshots and Astra all serve.

Values come from developers.openai.com model and pricing pages, not from
estimates. Standard-tier prices per 1M tokens:

    gpt-6-astra    $10.00 in / $1.00 cached / $12.50 cache-write / $50.00 out
    gpt-5.6-sol     $4.00 / $0.40 / $5.00  / $20.00
    gpt-5.6-terra   $2.00 / $0.20 / $2.50  / $12.00
    gpt-5.6-luna    $0.20 / $0.02 / $0.25  / $1.20

5.6 is the first OpenAI family to bill cache writes (1.25x uncached input), so
cache_write_per_million is populated here where the 5.4/5.5 rows leave it NULL.
Batch and Flex bill at 0.5x and Fast mode at 2x for all four -- verified row by
row in the pricing tables -- which is the existing openai-track service_tiers
shape. Prompts over 272K input tokens bill at 2x input and 1.5x output for the
whole request; that is recorded in availability rather than in the rate columns,
which describe the short-context case.

supports_pdf is false for all four even though the 5.4 and 5.5 rows set it true.
The model pages list input modalities as "text, image" and the supported-feature
lists carry image_input but no PDF input. file_search is offered as a tool, which
is retrieval, not native PDF input. Copying 5.5's flag would have invented a
capability, so this follows the documentation.

knowledge_cutoff and release_date are published: 2026-02-16 and 2026-07-09 for
the 5.6 tiers (GA July 9, corroborated by the Bedrock GA notice of July 13), and
2026-04-30 and 2026-09-03 for Astra.

The six score_* columns are house routing weights, as elsewhere in this table,
not published benchmarks. They are ordered from Artificial Analysis' July 9
measurements -- Intelligence Index 59/55/51 and Coding Agent Index 80/77/75 for
Sol/Terra/Luna -- with Astra placed above Sol. The Terra-to-Luna gap is kept
narrow because the measured gap is narrow.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f1a9c37d2b64"
down_revision: str | Sequence[str] | None = "e83b1d4f0a72"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_LONG_CONTEXT = "input_over_272k_bills_2x_input_1.5x_output"
_SOL_PROMO = "promotional_pricing_through_2026-11-21"

#: One entry per model, shared by both provider tracks. ``cost`` and
#: ``cache_*`` describe the metered openai/* row only; the codex/* row is
#: written at 0 because the subscription does not bill per token.
MODELS = [
    {
        "suffix": "gpt-6-astra",
        "name": "GPT-6 Astra",
        "hint": "Hardest end-to-end work",
        "family": "gpt",
        "speed_tier": "medium",
        "score_coding": 100,
        "score_reasoning": 100,
        "score_planning": 95,
        "score_tool_use": 96,
        "score_instruction": 96,
        "score_design": 88,
        "cost_input_per_m": 10.0,
        "cost_output_per_m": 50.0,
        "cache_read_per_million": 1.0,
        "cache_write_per_million": 12.5,
        "release_date": "2026-09-03",
        "knowledge_cutoff": "2026-04-30",
        "openai_availability": f"{_LONG_CONTEXT}; fast_mode_unavailable_with_eu_data_residency",
        "openai_alias": "astra",
        "codex_alias": "codex-astra",
    },
    {
        "suffix": "gpt-5.6-sol",
        "name": "GPT-5.6 Sol",
        "hint": "Flagship",
        "family": "gpt",
        "speed_tier": "medium",
        "score_coding": 99,
        "score_reasoning": 99,
        "score_planning": 92,
        "score_tool_use": 93,
        "score_instruction": 95,
        "score_design": 86,
        "cost_input_per_m": 4.0,
        "cost_output_per_m": 20.0,
        "cache_read_per_million": 0.4,
        "cache_write_per_million": 5.0,
        "release_date": "2026-07-09",
        "knowledge_cutoff": "2026-02-16",
        "openai_availability": f"{_LONG_CONTEXT}; {_SOL_PROMO}",
        "openai_alias": "sol",
        "codex_alias": "codex-sol",
    },
    {
        "suffix": "gpt-5.6-terra",
        "name": "GPT-5.6 Terra",
        "hint": "Balanced",
        "family": "gpt",
        "speed_tier": "fast",
        "score_coding": 90,
        "score_reasoning": 91,
        "score_planning": 82,
        "score_tool_use": 85,
        "score_instruction": 91,
        "score_design": 78,
        "cost_input_per_m": 2.0,
        "cost_output_per_m": 12.0,
        "cache_read_per_million": 0.2,
        "cache_write_per_million": 2.5,
        "release_date": "2026-07-09",
        "knowledge_cutoff": "2026-02-16",
        "openai_availability": _LONG_CONTEXT,
        "openai_alias": "terra",
        "codex_alias": "codex-terra",
    },
    {
        "suffix": "gpt-5.6-luna",
        "name": "GPT-5.6 Luna",
        "hint": "Cheap high volume",
        "family": "gpt",
        "speed_tier": "fast",
        "score_coding": 88,
        "score_reasoning": 88,
        "score_planning": 78,
        "score_tool_use": 82,
        "score_instruction": 90,
        "score_design": 74,
        "cost_input_per_m": 0.2,
        "cost_output_per_m": 1.2,
        "cache_read_per_million": 0.02,
        "cache_write_per_million": 0.25,
        "release_date": "2026-07-09",
        "knowledge_cutoff": "2026-02-16",
        "openai_availability": (
            f"{_LONG_CONTEXT}; no_fine_tuning; no_realtime_api; no_assistants_api"
        ),
        "openai_alias": "luna",
        "codex_alias": "codex-luna",
    },
]

_OPENAI_TIERS = json.dumps({"flex": 0.5, "default": 1.0, "priority": 2.0})
_CODEX_TIERS = json.dumps({"default": 1.0})

#: sort_order is a global display slot, not a key: gemini already puts four
#: rows on slot 4 and the listing tie-breaks on id. Rather than renumber two
#: whole provider blocks, the new rows join the slot their track's current
#: flagship occupies -- openai/gpt-5.5 on 11, codex/gpt-5.5 on 16 -- which
#: lands the 5.6 tiers and Astra next to 5.5 and ahead of the 5.4 rows.
_OPENAI_SORT_ORDER = 11
_CODEX_SORT_ORDER = 16

UPSERT_SQL = sa.text(
    """
    INSERT INTO models (
        id, alias, name, hint, provider,
        score_coding, score_reasoning, score_planning, score_tool_use,
        score_instruction, score_design,
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
        :id, :alias, :name, :hint, :provider,
        :score_coding, :score_reasoning, :score_planning, :score_tool_use,
        :score_instruction, :score_design,
        :cost_input_per_m, :cost_output_per_m, 'per_million_tokens', NULL,
        CAST(:service_tiers AS jsonb),
        :cache_read_per_million, :cache_write_per_million,
        1050000, :speed_tier,
        false, true, false, true,
        false, false, true, true,
        true, :supports_session_cache, 128000,
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
        cache_write_per_million = EXCLUDED.cache_write_per_million,
        context_window = EXCLUDED.context_window,
        max_output_tokens = EXCLUDED.max_output_tokens,
        speed_tier = EXCLUDED.speed_tier,
        has_vision = EXCLUDED.has_vision,
        has_thinking = EXCLUDED.has_thinking,
        supports_pdf = EXCLUDED.supports_pdf,
        supports_audio = EXCLUDED.supports_audio,
        supports_tool_execution = EXCLUDED.supports_tool_execution,
        supports_verbosity = EXCLUDED.supports_verbosity,
        supports_xhigh = EXCLUDED.supports_xhigh,
        supports_session_cache = EXCLUDED.supports_session_cache,
        release_date = EXCLUDED.release_date,
        knowledge_cutoff = EXCLUDED.knowledge_cutoff,
        family = EXCLUDED.family,
        availability = EXCLUDED.availability,
        is_active = true,
        sort_order = EXCLUDED.sort_order,
        updated_at = now()
    """
)


def _rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for entry in MODELS:
        shared = {
            key: entry[key]
            for key in (
                "name",
                "hint",
                "family",
                "speed_tier",
                "score_coding",
                "score_reasoning",
                "score_planning",
                "score_tool_use",
                "score_instruction",
                "score_design",
                "release_date",
                "knowledge_cutoff",
            )
        }
        rows.append(
            {
                **shared,
                "id": f"openai/{entry['suffix']}",
                "alias": entry["openai_alias"],
                "provider": "openai",
                "cost_input_per_m": entry["cost_input_per_m"],
                "cost_output_per_m": entry["cost_output_per_m"],
                "cache_read_per_million": entry["cache_read_per_million"],
                "cache_write_per_million": entry["cache_write_per_million"],
                "service_tiers": _OPENAI_TIERS,
                "supports_session_cache": False,
                "availability": entry["openai_availability"],
                "sort_order": _OPENAI_SORT_ORDER,
            }
        )
        rows.append(
            {
                **shared,
                "id": f"codex/{entry['suffix']}",
                "alias": entry["codex_alias"],
                "provider": "codex",
                # The OAuth subscription does not bill per token; every other
                # codex/* row carries 0 for the same reason.
                "cost_input_per_m": 0.0,
                "cost_output_per_m": 0.0,
                "cache_read_per_million": None,
                "cache_write_per_million": None,
                "service_tiers": _CODEX_TIERS,
                "supports_session_cache": True,
                "availability": "codex_oauth_subscription",
                "sort_order": _CODEX_SORT_ORDER,
            }
        )
    return rows


def upgrade() -> None:
    bind = op.get_bind()
    for row in _rows():
        bind.execute(UPSERT_SQL, row)


def downgrade() -> None:
    ids = [row["id"] for row in _rows()]
    op.get_bind().execute(
        sa.text("DELETE FROM models WHERE id = ANY(:ids)"),
        {"ids": ids},
    )
