"""Insert-only seed entries for UI-selectable models; DB is runtime source."""

from __future__ import annotations

from app.constants.catalog_types import (
    ModelCapabilities,
    ModelCost,
    ModelEntry,
    ModelScores,
)
from app.constants.models import (
    CF_FLUX_1_SCHNELL,
    CF_FLUX_2_KLEIN_9B,
    CF_GEMMA_4_26B,
    CF_GLM_4_7_FLASH,
    CF_GPT_OSS_20B,
    CF_GPT_OSS_120B,
    CF_GRANITE_4_H_MICRO,
    CF_LEONARDO_LUCID,
    CF_LEONARDO_PHOENIX,
    CF_LLAMA_4_SCOUT,
    CF_MISTRAL_SMALL,
    CF_NEMOTRON_3_120B,
    CF_QWEN2_5_CODER,
    CF_QWEN3_30B,
    CF_QWQ_32B,
    CF_SD_XL_LIGHTNING,
    CLAUDE_HAIKU,
    CLAUDE_OPUS,
    CLAUDE_SONNET,
    CODEX_GPT_5_6_LUNA,
    CODEX_GPT_5_6_SOL,
    CODEX_GPT_5_6_TERRA,
    CODEX_GPT_6_1_SOL,
    CODEX_GPT_6_ASTRA,
    CODEX_GPT_6_LUNA,
    CODEX_GPT_6_SOL,
    CODEX_GPT_DAYBREAK_BLUE,
    GEMINI_2_5_FLASH,
    GEMINI_2_5_FLASH_LITE,
    GEMINI_3_1_FLASH_LITE,
    GEMINI_3_5_FLASH,
    GEMINI_3_5_FLASH_LITE,
    GEMINI_3_6_FLASH,
    GEMINI_3_7_FLASH,
    GEMINI_3_8_FLASH,
    LOCAL_GEMMA_4_12B,
    LOCAL_QWEN3_8_27B_IQ3_S,
    LOCAL_QWEN3_VL_8B_INSTRUCT,
    NVIDIA_FLUX_1_DEV,
    NVIDIA_FLUX_1_KONTEXT,
    NVIDIA_GLM_5_3,
    NVIDIA_GPT_OSS_20B,
    NVIDIA_NEMOTRON_3_5_LIGHTNING,
    NVIDIA_NEMOTRON_3_SUPER,
    XAI_GROK_4_3,
    XAI_GROK_4_20,
    XAI_GROK_4_20_MULTI_AGENT,
)

_CODEX_CAPABILITIES = ModelCapabilities(
    has_vision=True, has_thinking=True, supports_tool_execution=True, supports_verbosity=True,
    supports_xhigh=True, supports_session_cache=True, max_output_tokens=128_000,
    # The Codex models endpoint lists low..xhigh (no minimal) for every model.
    thinking_level_map={"minimal": "low"},
)
_CLAUDE_CAPABILITIES = ModelCapabilities(
    has_vision=True, has_thinking=True, supports_pdf=True, supports_xhigh=True, max_output_tokens=128_000,
    # The CLI's --effort takes low..max; Agent Hub has no separate minimal level there.
    thinking_level_map={"minimal": "low"},
)
_CLAUDE_AVAILABILITY = "claude_code_cli_subscription; verified_2026-10-09; prices_platform.claude.com_2026-10-09"

# Single place to register UI-visible models. Everything else derives from this.
# Static prices are current list prices checked 2026-05-07; DB enrichment may overlay.
MODEL_CATALOG: list[ModelEntry] = [
    # --- Claude ---
    # Served by the headless Claude Code CLI on the owner's subscription; the CLI
    # runs tool-denied, so Agent Hub tool requests fall back to tool-capable models.
    # Prices and limits from platform.claude.com, checked 2026-10-09. Scores are
    # inherited from the 4.x predecessors until measured.
    ModelEntry(
        id=CLAUDE_HAIKU, alias="haiku", name="Claude Haiku 5.5",
        hint="Fast, cheap; scores inherited from Haiku 4.5", provider="claude",
        scores=ModelScores(coding=73, reasoning=70, planning=50, tool_use=65, instruction=65, design=60),
        cost=ModelCost(0.10, 0.50, cache_read_per_million=0.01, cache_write_per_million=0.125),
        context_window=1_000_000, speed_tier="fast",
        capabilities=_CLAUDE_CAPABILITIES,
        release_date="2026-10-07", knowledge_cutoff="2026-06", family="claude-haiku",
        availability=_CLAUDE_AVAILABILITY + "; prompts_over_100k_billed_0.50_2.50",
    ),
    ModelEntry(
        id=CLAUDE_SONNET, alias="sonnet", name="Claude Sonnet 5.5",
        hint="Balanced; design, critique and writing; scores inherited from Sonnet 4.6", provider="claude",
        scores=ModelScores(coding=80, reasoning=87, planning=72, tool_use=78, instruction=84, design=72),
        cost=ModelCost(2.00, 10.00, cache_read_per_million=0.10, cache_write_per_million=2.50),
        context_window=1_000_000, speed_tier="medium",
        capabilities=_CLAUDE_CAPABILITIES,
        release_date="2026-09-28", knowledge_cutoff="2026-06", family="claude-sonnet",
        availability=_CLAUDE_AVAILABILITY,
    ),
    ModelEntry(
        id=CLAUDE_OPUS, alias="opus", name="Claude Opus 5.5",
        hint="Hard judgment; scores inherited from Opus 4.7", provider="claude",
        scores=ModelScores(coding=85, reasoning=93, planning=74, tool_use=78, instruction=86, design=72),
        cost=ModelCost(4.00, 20.00, cache_read_per_million=0.20, cache_write_per_million=5.00),
        context_window=1_000_000, speed_tier="medium",
        capabilities=_CLAUDE_CAPABILITIES,
        release_date="2026-09-22", knowledge_cutoff="2026-06", family="claude-opus",
        availability=_CLAUDE_AVAILABILITY,
    ),

    # --- Gemini ---
    # Official model/pricing docs checked 2026-09-12. No benchmark scores
    # have been verified; zero denotes unmeasured here, not a quality result.
    ModelEntry(
        id=GEMINI_3_5_FLASH_LITE, alias="3.5-flash-lite", name="Gemini 3.5 Flash-Lite",
        hint="Routine extraction; benchmarks unmeasured", provider="gemini",
        scores=ModelScores(coding=0, reasoning=0, planning=0, tool_use=0, instruction=0, design=0),
        cost=ModelCost(0.30, 2.50, cache_read_per_million=0.03),
        context_window=1_048_576, speed_tier="fast",
        capabilities=ModelCapabilities(has_vision=True, has_thinking=True, supports_pdf=True, supports_audio=True, supports_tool_execution=True, max_output_tokens=65_536),
        family="gemini-flash-lite",
        availability="stable; free_tier_no_search_grounding; benchmarks_unmeasured",
    ),
    ModelEntry(
        id=GEMINI_3_8_FLASH, alias="3.8-flash", name="Gemini 3.8 Flash",
        hint="Agentic flagship", provider="gemini",
        scores=ModelScores(coding=89, reasoning=95, planning=88, tool_use=91, instruction=92, design=90),
        cost=ModelCost(
            0.75, 3.75,
            cache_read_per_million=0.075,
            service_tiers={"default": 1.0, "batch": 0.5, "flex": 0.5, "priority": 1.8},
        ),
        context_window=1_048_576, speed_tier="fast",
        capabilities=ModelCapabilities(has_vision=True, has_thinking=True, supports_pdf=True, supports_audio=True, supports_tool_execution=True, max_output_tokens=65_536, thinking_level_map={"minimal": "low"}),
        # knowledge_cutoff is left unset: Google's model page states a September
        # 2026 "latest update" but publishes no training cutoff for this model.
        release_date="2026-09-01", family="gemini-flash",
        # Free tier covers input, output and context caching; Google Search
        # grounding is the one thing it does not cover. Thinking is low/medium/
        # high only — this model has no "minimal" level.
        availability="stable; free_tier_no_search_grounding; promo_pricing_through_2026-12-31_then_1.50_7.50",
    ),
    ModelEntry(
        id=GEMINI_3_7_FLASH, alias="3.7-flash", name="Gemini 3.7 Flash",
        hint="Agentic flagship", provider="gemini",
        scores=ModelScores(coding=88, reasoning=95, planning=87, tool_use=90, instruction=91, design=90),
        cost=ModelCost(
            0.75, 3.75,
            cache_read_per_million=0.075,
            service_tiers={"default": 1.0, "batch": 0.5, "flex": 0.5, "priority": 1.8},
        ),
        context_window=1_048_576, speed_tier="fast",
        capabilities=ModelCapabilities(has_vision=True, has_thinking=True, supports_pdf=True, supports_audio=True, supports_tool_execution=True, max_output_tokens=65_536, thinking_level_map={"minimal": "low"}),
        release_date="2026-08-01", knowledge_cutoff="2025-01-01", family="gemini-flash",
        availability="stable; free_tier; promo_pricing_through_2026-12-31_then_1.50_7.50",
    ),
    ModelEntry(
        id=GEMINI_3_6_FLASH, alias="3.6-flash", name="Gemini 3.6 Flash",
        hint="Agentic flash; scores inherited from Gemini 3.5 Flash", provider="gemini",
        scores=ModelScores(coding=85, reasoning=94, planning=84, tool_use=86, instruction=90, design=90),
        cost=ModelCost(
            0.75, 3.75,
            cache_read_per_million=0.075,
            service_tiers={"default": 1.0, "batch": 0.5, "flex": 0.5, "priority": 1.8},
        ),
        context_window=1_048_576, speed_tier="fast",
        capabilities=ModelCapabilities(has_vision=True, has_thinking=True, supports_pdf=True, supports_audio=True, supports_tool_execution=True, max_output_tokens=65_536),
        family="gemini-flash",
        availability="stable; free_tier; verified_2026-10-09; promo_pricing_through_2026-12-31_then_1.50_7.50",
    ),
    ModelEntry(
        id=GEMINI_3_5_FLASH, alias="3.5-flash", name="Gemini 3.5 Flash",
        hint="Frontier speed", provider="gemini",
        scores=ModelScores(coding=85, reasoning=94, planning=84, tool_use=86, instruction=90, design=90),
        cost=ModelCost(
            1.50, 9.00,
            cache_read_per_million=0.15,
            service_tiers={"default": 1.0, "batch": 0.5, "flex": 0.5, "priority": 1.8},
        ),
        context_window=1_048_576, speed_tier="fast",
        capabilities=ModelCapabilities(has_vision=True, has_thinking=True, supports_pdf=True, supports_audio=True, supports_tool_execution=True, max_output_tokens=65_536),
        release_date="2026-05-19", knowledge_cutoff="2025-01-01", family="gemini-flash",
        availability="stable; free_tier; quotas_project_specific_ai_studio",
    ),
    ModelEntry(
        id=GEMINI_3_1_FLASH_LITE, alias="3.1-flash-lite", name="Gemini 3.1 Flash-Lite",
        hint="High throughput", provider="gemini",
        scores=ModelScores(coding=56, reasoning=64, planning=46, tool_use=49, instruction=86, design=58),
        cost=ModelCost(
            0.25, 1.50,
            cache_read_per_million=0.025,
            service_tiers={"default": 1.0, "batch": 0.5, "flex": 0.5, "priority": 1.8},
        ),
        context_window=1_048_576, speed_tier="fast",
        capabilities=ModelCapabilities(has_vision=True, has_thinking=True, supports_pdf=True, supports_audio=True, supports_tool_execution=True, max_output_tokens=65_536),
        release_date="2026-05-07", knowledge_cutoff="2025-01-01", family="gemini-flash-lite",
        availability="stable; free_tier; shutdown_earliest_2027-05-07_replacement_gemini-3.5-flash-lite",
    ),
    ModelEntry(
        id=GEMINI_2_5_FLASH, alias="2.5-flash", name="Gemini 2.5 Flash",
        hint="Price performance", provider="gemini",
        scores=ModelScores(coding=72, reasoning=84, planning=68, tool_use=70, instruction=84, design=78),
        cost=ModelCost(
            0.30, 2.50,
            cache_read_per_million=0.03,
            service_tiers={"default": 1.0, "batch": 0.5, "flex": 0.5, "priority": 1.8},
        ),
        context_window=1_048_576, speed_tier="fast",
        capabilities=ModelCapabilities(has_vision=True, has_thinking=True, supports_pdf=True, supports_audio=True, supports_tool_execution=True, max_output_tokens=65_536),
        release_date="2025-06-17", knowledge_cutoff="2025-01-01", family="gemini-flash",
        availability="free_tier; quotas_project_specific_ai_studio",
    ),
    ModelEntry(
        id=GEMINI_2_5_FLASH_LITE, alias="flash-lite", name="Gemini 2.5 Flash-Lite",
        hint="Cheap", provider="gemini",
        scores=ModelScores(coding=34, reasoning=50, planning=40, tool_use=45, instruction=84, design=55),
        cost=ModelCost(
            0.10, 0.40,
            cache_read_per_million=0.01,
            service_tiers={"default": 1.0, "batch": 0.5, "flex": 0.5, "priority": 1.8},
        ),
        context_window=1_048_576, speed_tier="fast",
        capabilities=ModelCapabilities(has_vision=True, has_thinking=True, supports_pdf=True, supports_audio=True, supports_tool_execution=True, max_output_tokens=65_536),
        release_date="2025-07-22", knowledge_cutoff="2025-01-01", family="gemini-flash-lite",
        availability="free_tier; quotas_project_specific_ai_studio",
    ),

    # --- Codex OAuth/subscription ---
    # Live-verified 2026-10-09 against the ChatGPT-account Codex endpoint, which
    # rejects gpt-5.1/5.2/5.3-codex and gpt-5.4/5.4-mini. Codex serves a 272k
    # context window on this route (models endpoint); API pages list 1.05M.
    # Model facts: developers.openai.com/api/docs/models/<id>. Scores marked
    # inherited copy the nearest predecessor's house weights, not benchmarks.
    ModelEntry(
        id=CODEX_GPT_6_1_SOL, alias="codex-gpt-6.1-sol", name="GPT-6.1 Sol",
        hint="General complex work", provider="codex",
        scores=ModelScores(coding=98, reasoning=99, planning=90, tool_use=91, instruction=94, design=82),
        cost=ModelCost(0.00, 0.00), context_window=272_000, speed_tier="medium",
        capabilities=_CODEX_CAPABILITIES, knowledge_cutoff="2026-04-30", family="gpt",
        availability="codex_oauth_subscription; verified_2026-10-09; reasoning_low_medium_high_xhigh_max_ultra",
    ),
    ModelEntry(
        id=CODEX_GPT_6_ASTRA, alias="codex-astra", name="GPT-6 Astra",
        hint="Hardest end-to-end work", provider="codex",
        scores=ModelScores(coding=100, reasoning=100, planning=95, tool_use=96, instruction=96, design=88),
        cost=ModelCost(0.00, 0.00), context_window=272_000, speed_tier="medium",
        capabilities=_CODEX_CAPABILITIES,
        release_date="2026-09-03", knowledge_cutoff="2026-04-30", family="gpt",
        availability="codex_oauth_subscription; verified_2026-10-09",
    ),
    ModelEntry(
        id=CODEX_GPT_6_SOL, alias="codex-6-sol", name="GPT-6 Sol",
        hint="Previous-generation workhorse; scores inherited from GPT-6.1 Sol", provider="codex",
        scores=ModelScores(coding=98, reasoning=99, planning=90, tool_use=91, instruction=94, design=82),
        cost=ModelCost(0.00, 0.00), context_window=272_000, speed_tier="medium",
        capabilities=_CODEX_CAPABILITIES, knowledge_cutoff="2026-04-20", family="gpt",
        availability="codex_oauth_subscription; verified_2026-10-09",
    ),
    ModelEntry(
        id=CODEX_GPT_6_LUNA, alias="codex-6-luna", name="GPT-6 Luna",
        hint="Fast, cheap everyday tasks; scores inherited from GPT-5.6 Luna", provider="codex",
        scores=ModelScores(coding=88, reasoning=88, planning=78, tool_use=82, instruction=90, design=74),
        cost=ModelCost(0.00, 0.00), context_window=272_000, speed_tier="fast",
        capabilities=_CODEX_CAPABILITIES, knowledge_cutoff="2026-05-18", family="gpt",
        availability="codex_oauth_subscription; verified_2026-10-09",
    ),
    ModelEntry(
        id=CODEX_GPT_5_6_SOL, alias="codex-sol", name="GPT-5.6 Sol",
        hint="Flagship", provider="codex",
        scores=ModelScores(coding=99, reasoning=99, planning=92, tool_use=93, instruction=95, design=86),
        cost=ModelCost(0.00, 0.00), context_window=272_000, speed_tier="medium",
        capabilities=_CODEX_CAPABILITIES,
        release_date="2026-07-09", knowledge_cutoff="2026-02-16", family="gpt",
        availability="codex_oauth_subscription; verified_2026-10-09",
    ),
    ModelEntry(
        id=CODEX_GPT_5_6_TERRA, alias="codex-terra", name="GPT-5.6 Terra",
        hint="Balanced", provider="codex",
        scores=ModelScores(coding=90, reasoning=91, planning=82, tool_use=85, instruction=91, design=78),
        cost=ModelCost(0.00, 0.00), context_window=272_000, speed_tier="fast",
        capabilities=_CODEX_CAPABILITIES,
        release_date="2026-07-09", knowledge_cutoff="2026-02-16", family="gpt",
        availability="codex_oauth_subscription; verified_2026-10-09",
    ),
    ModelEntry(
        id=CODEX_GPT_5_6_LUNA, alias="codex-luna", name="GPT-5.6 Luna",
        hint="Cheap high volume", provider="codex",
        scores=ModelScores(coding=88, reasoning=88, planning=78, tool_use=82, instruction=90, design=74),
        cost=ModelCost(0.00, 0.00), context_window=272_000, speed_tier="fast",
        capabilities=_CODEX_CAPABILITIES,
        release_date="2026-07-09", knowledge_cutoff="2026-02-16", family="gpt",
        availability="codex_oauth_subscription; verified_2026-10-09",
    ),
    ModelEntry(
        id=CODEX_GPT_DAYBREAK_BLUE, alias="codex-daybreak", name="GPT Daybreak Blue",
        hint="Defensive cybersecurity (Daybreak Blue access program)", provider="codex",
        scores=ModelScores(coding=99, reasoning=99, planning=92, tool_use=93, instruction=95, design=86),
        cost=ModelCost(0.00, 0.00), context_window=272_000, speed_tier="medium",
        capabilities=_CODEX_CAPABILITIES, knowledge_cutoff="2026-02-16", family="gpt",
        availability=(
            "codex_oauth_subscription; verified_2026-10-09; rolling_alias_no_snapshot; "
            "needs_access_programs_cyber_daybreak_blue; openai_api_alias_deprecated_snapshot_gpt-5.6-sol"
        ),
        access_programs={"cyber": "daybreak_blue"},
    ),

    # --- xAI direct ---
    ModelEntry(
        id=XAI_GROK_4_3, alias="grok", name="Grok 4.3",
        hint="xAI current", provider="xai",
        scores=ModelScores(coding=78, reasoning=88, planning=82, tool_use=84, instruction=84, design=72),
        cost=ModelCost(1.25, 2.50), context_window=1_000_000, speed_tier="fast",
        capabilities=ModelCapabilities(has_vision=True, has_thinking=True, supports_tool_execution=True, supports_session_cache=True, max_output_tokens=32_768),
        release_date="2026-04-30", family="grok",
    ),
    ModelEntry(
        id=XAI_GROK_4_20, alias="grok-4.20", name="Grok 4.20 Reasoning",
        hint="2M context", provider="xai",
        scores=ModelScores(coding=75, reasoning=88, planning=86, tool_use=84, instruction=84, design=72),
        cost=ModelCost(1.25, 2.50), context_window=2_000_000, speed_tier="fast",
        capabilities=ModelCapabilities(has_vision=True, has_thinking=True, supports_tool_execution=True, supports_session_cache=True, max_output_tokens=32_768),
        release_date="2026-03-09", family="grok-4.20",
    ),
    ModelEntry(
        id=XAI_GROK_4_20_MULTI_AGENT, alias="grok-research", name="Grok 4.20 Multi-Agent",
        hint="Deep research", provider="xai",
        scores=ModelScores(coding=72, reasoning=91, planning=94, tool_use=70, instruction=86, design=68),
        cost=ModelCost(1.25, 2.50), context_window=2_000_000, speed_tier="medium",
        capabilities=ModelCapabilities(has_thinking=True, supports_session_cache=True, max_output_tokens=32_768),
        release_date="2026-03-09", family="grok-4.20",
    ),

    # --- Local OpenAI-compatible ---
    ModelEntry(
        id=LOCAL_GEMMA_4_12B, alias="local/gemma", name="Gemma 4 12B QAT (Local)",
        hint="Local multimodal", provider="local",
        scores=ModelScores(coding=52, reasoning=64, planning=56, tool_use=60, instruction=74, design=55),
        cost=ModelCost(0.00, 0.00), context_window=32_768, speed_tier="fast",
        capabilities=ModelCapabilities(has_vision=True, supports_tool_execution=True, max_output_tokens=8_192),
        release_date="2026-06-03", family="gemma",
        availability="requires_local_openai_endpoint; qat_q4_0_~8gb_vram_100pct_gpu",
    ),
    ModelEntry(
        id=LOCAL_QWEN3_8_27B_IQ3_S,
        alias="local/qwen3.8",
        name="Qwen3.8 27B GSQ/RCO IQ3_S (Local)",
        hint="Local coding and reasoning worker",
        provider="local",
        scores=ModelScores(coding=86, reasoning=89, planning=82, tool_use=75, instruction=88, design=65),
        cost=ModelCost(0.00, 0.00),
        context_window=32_768,
        speed_tier="medium",
        capabilities=ModelCapabilities(
            has_thinking=True,
            supports_tool_execution=True,
            supports_xhigh=True,
            max_output_tokens=8_192,
        ),
        release_date="2026-09-01",
        family="qwen",
        availability="local_ollama_or_llama_server; iq3_s_11.8gb_~12gb_vram",
    ),
    ModelEntry(
        id=LOCAL_QWEN3_VL_8B_INSTRUCT, alias="local/qwen-vl", name="Qwen3-VL 8B Instruct (Local)",
        hint="Local receipt/document OCR", provider="local",
        scores=ModelScores(coding=48, reasoning=60, planning=52, tool_use=56, instruction=78, design=50),
        cost=ModelCost(0.00, 0.00), context_window=32_768, speed_tier="fast",
        capabilities=ModelCapabilities(has_vision=True, supports_tool_execution=True, max_output_tokens=16_384),
        release_date="2026-02-01", family="qwen",
        # Scored 16/16 line items, exact subtotal/tax/total on a real Walmart thermal
        # receipt photo in 12s. Dynamic-resolution tiling is what Gemma 4 lacks: Gemma
        # bills one 256-token tile for the whole page, Qwen3-VL bills ~4.1k.
        availability="requires_local_openai_endpoint; ~6.1gb_vram; use_instruct_not_bare_8b_tag",
    ),

    # --- NVIDIA NIM (free tier; all below probed live 2026-10-09) ---
    ModelEntry(
        id=NVIDIA_NEMOTRON_3_SUPER, alias="nv/nemotron", name="Nemotron 3 Super 120B-A12B (NVIDIA)",
        upstream_id="nvidia/nemotron-3-super-120b-a12b",
        hint="Free MoE", provider="nvidia",
        scores=ModelScores(coding=82, reasoning=88, planning=84, tool_use=85, instruction=86, design=66),
        cost=ModelCost(0.00, 0.00), context_window=131_072, speed_tier="medium",
        capabilities=ModelCapabilities(has_thinking=True, supports_tool_execution=True, max_output_tokens=32_768),
        release_date="2026-05-01", family="nemotron",
        availability="nvidia_dev_free_endpoint",
    ),
    ModelEntry(
        id=NVIDIA_NEMOTRON_3_5_LIGHTNING, alias="nv/lightning", name="Nemotron 3.5 Lightning 30B-A3B (NVIDIA)",
        upstream_id="nvidia/nemotron-3.5-lightning-30b-a3b",
        hint="Free fast", provider="nvidia",
        scores=ModelScores(coding=74, reasoning=78, planning=76, tool_use=80, instruction=80, design=60),
        cost=ModelCost(0.00, 0.00), context_window=131_072, speed_tier="fast",
        capabilities=ModelCapabilities(has_thinking=True, supports_tool_execution=True, max_output_tokens=32_768),
        release_date="2026-08-14", family="nemotron",
        availability="nvidia_dev_free_endpoint; apache_2_0",
    ),
    ModelEntry(
        id=NVIDIA_GLM_5_3, alias="nv/glm", name="GLM-5.3 (NVIDIA)",
        upstream_id="z-ai/glm-5.3",
        hint="Free strong generalist; scores inherited from GLM-5.2", provider="nvidia",
        scores=ModelScores(coding=91, reasoning=92, planning=88, tool_use=89, instruction=88, design=82),
        cost=ModelCost(0.00, 0.00), context_window=1_048_576, speed_tier="medium",
        capabilities=ModelCapabilities(has_thinking=True, supports_tool_execution=True, max_output_tokens=32_768),
        release_date="2026-08-27", family="glm",
        # docs.api.nvidia.com/nim/reference/z-ai-glm-5-3; reasoning_effort low/high/max.
        availability="nvidia_dev_free_endpoint; verified_2026-10-09",
    ),
    ModelEntry(
        id=NVIDIA_GPT_OSS_20B, alias="nv/gpt-oss-20b", name="GPT-OSS 20B (NVIDIA)",
        upstream_id="openai/gpt-oss-20b",
        hint="Free fast; scores inherited from Cloudflare GPT-OSS 20B", provider="nvidia",
        scores=ModelScores(coding=58, reasoning=62, planning=50, tool_use=55, instruction=70, design=50),
        cost=ModelCost(0.00, 0.00), context_window=128_000, speed_tier="fast",
        capabilities=ModelCapabilities(has_thinking=True, supports_tool_execution=True, max_output_tokens=8_192),
        release_date="2025-08-05", family="gpt-oss",
        availability="nvidia_dev_free_endpoint; verified_2026-10-09; apache_2_0",
    ),

    # --- NVIDIA image ---
    ModelEntry(
        id=NVIDIA_FLUX_1_DEV, alias="nv/flux-dev", name="FLUX.1-dev (NVIDIA)",
        upstream_id="black-forest-labs/flux.1-dev",
        hint="Image gen", provider="nvidia",
        scores=ModelScores(coding=0, reasoning=0, planning=0, tool_use=0, instruction=40, design=88),
        cost=ModelCost(0.00, 0.00, pricing_unit="per_image", unit_price=0.00), context_window=0, speed_tier="slow",
        capabilities=ModelCapabilities(can_generate_images=True, max_output_tokens=0),
        release_date="2024-12-01", family="flux",
    ),
    ModelEntry(
        id=NVIDIA_FLUX_1_KONTEXT, alias="nv/flux-kontext", name="FLUX.1-Kontext (NVIDIA)",
        upstream_id="black-forest-labs/flux.1-kontext-dev",
        hint="Image edit", provider="nvidia",
        scores=ModelScores(coding=0, reasoning=0, planning=0, tool_use=0, instruction=50, design=90),
        cost=ModelCost(0.00, 0.00, pricing_unit="per_image", unit_price=0.00), context_window=0, speed_tier="medium",
        capabilities=ModelCapabilities(can_generate_images=True, can_edit_images=True, max_output_tokens=0),
        release_date="2025-06-01", family="flux",
    ),

    # --- Cloudflare Workers AI LLM ---
    ModelEntry(
        id=CF_GLM_4_7_FLASH, alias="cf/glm", name="GLM-4.7-Flash (Cloudflare)",
        upstream_id="@cf/zai-org/glm-4.7-flash",
        hint="Very cheap", provider="cloudflare",
        scores=ModelScores(coding=58, reasoning=66, planning=52, tool_use=62, instruction=72, design=52),
        cost=ModelCost(0.0605, 0.40), context_window=131_072, speed_tier="fast",
        capabilities=ModelCapabilities(has_thinking=True, supports_tool_execution=True, max_output_tokens=16_384),
        release_date="2026-01-15", family="glm",
        availability="workers_free_plan_10k_neurons_per_day; list_price_from_cloudflare_models_api_2026-10-09",
    ),
    ModelEntry(
        id=CF_QWEN3_30B, alias="cf/qwen3", name="Qwen3 30B-A3B (Cloudflare)",
        upstream_id="@cf/qwen/qwen3-30b-a3b-fp8",
        hint="Cheap thinking", provider="cloudflare",
        scores=ModelScores(coding=60, reasoning=70, planning=55, tool_use=55, instruction=68, design=50),
        cost=ModelCost(0.0509, 0.335), context_window=32_768, speed_tier="fast",
        capabilities=ModelCapabilities(has_thinking=True, supports_tool_execution=True, max_output_tokens=8_192),
        release_date="2025-05-01", family="qwen",
        availability="workers_free_plan_10k_neurons_per_day; list_price_from_cloudflare_models_api_2026-10-09",
    ),
    ModelEntry(
        id=CF_GPT_OSS_120B, alias="cf/gpt-oss", name="GPT-OSS 120B (Cloudflare)",
        upstream_id="@cf/openai/gpt-oss-120b",
        hint="OSS general", provider="cloudflare",
        scores=ModelScores(coding=68, reasoning=74, planning=60, tool_use=62, instruction=74, design=55),
        cost=ModelCost(0.35, 0.75), context_window=128_000, speed_tier="medium",
        capabilities=ModelCapabilities(has_thinking=True, supports_tool_execution=True, max_output_tokens=16_384),
        release_date="2026-04-01", family="gpt-oss",
        availability="workers_free_plan_10k_neurons_per_day; list_price_from_cloudflare_models_api_2026-10-09",
    ),
    ModelEntry(
        id=CF_GPT_OSS_20B, alias="cf/gpt-oss-20b", name="GPT-OSS 20B (Cloudflare)",
        upstream_id="@cf/openai/gpt-oss-20b",
        hint="OSS cheap", provider="cloudflare",
        scores=ModelScores(coding=58, reasoning=62, planning=50, tool_use=55, instruction=70, design=50),
        cost=ModelCost(0.20, 0.30), context_window=128_000, speed_tier="fast",
        capabilities=ModelCapabilities(has_thinking=True, supports_tool_execution=True, max_output_tokens=8_192),
        release_date="2026-04-01", family="gpt-oss",
        availability="workers_free_plan_10k_neurons_per_day; list_price_from_cloudflare_models_api_2026-10-09",
    ),
    ModelEntry(
        id=CF_LLAMA_4_SCOUT, alias="cf/llama", name="Llama 4 Scout 17B (Cloudflare)",
        upstream_id="@cf/meta/llama-4-scout-17b-16e-instruct",
        hint="Multimodal", provider="cloudflare",
        scores=ModelScores(coding=55, reasoning=60, planning=50, tool_use=50, instruction=65, design=55),
        cost=ModelCost(0.270, 0.850), context_window=131_000, speed_tier="fast",
        capabilities=ModelCapabilities(has_vision=True, supports_tool_execution=True, max_output_tokens=8_192),
        release_date="2025-04-01", family="llama",
        availability="workers_free_plan_10k_neurons_per_day; list_price_from_cloudflare_models_api_2026-10-09",
    ),
    ModelEntry(
        id=CF_QWQ_32B, alias="cf/qwq", name="QwQ 32B (Cloudflare)",
        upstream_id="@cf/qwen/qwq-32b",
        hint="Reasoning", provider="cloudflare",
        scores=ModelScores(coding=62, reasoning=75, planning=58, tool_use=52, instruction=66, design=48),
        cost=ModelCost(0.660, 1.000), context_window=24_000, speed_tier="medium",
        capabilities=ModelCapabilities(has_thinking=True, max_output_tokens=8_192),
        release_date="2025-03-01", family="qwen",
        availability="workers_free_plan_10k_neurons_per_day; list_price_from_cloudflare_models_api_2026-10-09",
    ),
    ModelEntry(
        id=CF_MISTRAL_SMALL, alias="cf/mistral", name="Mistral Small 3.1 24B (Cloudflare)",
        upstream_id="@cf/mistralai/mistral-small-3.1-24b-instruct",
        hint="Fast general", provider="cloudflare",
        scores=ModelScores(coding=58, reasoning=62, planning=50, tool_use=55, instruction=70, design=52),
        cost=ModelCost(0.351, 0.555), context_window=128_000, speed_tier="fast",
        capabilities=ModelCapabilities(has_vision=True, supports_tool_execution=True, max_output_tokens=8_192),
        release_date="2025-03-01", family="mistral",
        availability="workers_free_plan_10k_neurons_per_day; list_price_from_cloudflare_models_api_2026-10-09",
    ),
    ModelEntry(
        id=CF_QWEN2_5_CODER, alias="cf/coder", name="Qwen2.5 Coder 32B (Cloudflare)",
        upstream_id="@cf/qwen/qwen2.5-coder-32b-instruct",
        hint="Code gen", provider="cloudflare",
        scores=ModelScores(coding=72, reasoning=60, planning=48, tool_use=50, instruction=62, design=40),
        cost=ModelCost(0.660, 1.000), context_window=32_768, speed_tier="fast",
        capabilities=ModelCapabilities(supports_tool_execution=True, max_output_tokens=8_192),
        release_date="2024-11-01", family="qwen",
        availability="workers_free_plan_10k_neurons_per_day; list_price_from_cloudflare_models_api_2026-10-09",
    ),
    ModelEntry(
        id=CF_GEMMA_4_26B, alias="cf/gemma", name="Gemma 4 26B (Cloudflare)",
        upstream_id="@cf/google/gemma-4-26b-a4b-it",
        hint="Cheap general", provider="cloudflare",
        scores=ModelScores(coding=56, reasoning=62, planning=50, tool_use=50, instruction=70, design=50),
        cost=ModelCost(0.10, 0.30), context_window=256_000, speed_tier="fast",
        capabilities=ModelCapabilities(supports_tool_execution=True, max_output_tokens=8_192),
        release_date="2026-04-01", family="gemma",
        availability="workers_free_plan_10k_neurons_per_day; list_price_from_cloudflare_models_api_2026-10-09",
    ),
    ModelEntry(
        id=CF_GRANITE_4_H_MICRO, alias="cf/granite", name="Granite 4.0-H Micro (Cloudflare)",
        upstream_id="@cf/ibm-granite/granite-4.0-h-micro",
        hint="Tiny cheap", provider="cloudflare",
        scores=ModelScores(coding=45, reasoning=50, planning=40, tool_use=42, instruction=62, design=40),
        cost=ModelCost(0.017, 0.112), context_window=131_000, speed_tier="fast",
        capabilities=ModelCapabilities(supports_tool_execution=True, max_output_tokens=4_096),
        release_date="2026-04-01", family="granite",
        availability="workers_free_plan_10k_neurons_per_day; list_price_from_cloudflare_models_api_2026-10-09",
    ),
    ModelEntry(
        id=CF_NEMOTRON_3_120B, alias="cf/nemotron", name="Nemotron 3 120B (Cloudflare)",
        upstream_id="@cf/nvidia/nemotron-3-120b-a12b",
        hint="Reasoning", provider="cloudflare",
        scores=ModelScores(coding=72, reasoning=84, planning=72, tool_use=70, instruction=80, design=58),
        cost=ModelCost(0.50, 1.50), context_window=256_000, speed_tier="medium",
        capabilities=ModelCapabilities(has_thinking=True, supports_tool_execution=True, max_output_tokens=16_384),
        release_date="2026-03-01", family="nemotron",
        availability="workers_free_plan_10k_neurons_per_day; list_price_from_cloudflare_models_api_2026-10-09",
    ),

    # --- Cloudflare image ---
    ModelEntry(
        id=CF_FLUX_2_KLEIN_9B, alias="cf/flux2", name="FLUX.2 [klein] 9B (Cloudflare)",
        upstream_id="@cf/black-forest-labs/flux-2-klein-9b",
        hint="Best image; scores inherited from FLUX.2-dev", provider="cloudflare",
        scores=ModelScores(coding=0, reasoning=0, planning=0, tool_use=0, instruction=45, design=90),
        cost=ModelCost(0.00, 0.00, pricing_unit="per_image", unit_price=0.00), context_window=0, speed_tier="medium",
        capabilities=ModelCapabilities(can_generate_images=True, can_edit_images=True, max_output_tokens=0),
        family="flux",
        availability="workers_free_plan_10k_neurons_per_day; verified_2026-10-09; multipart_with_up_to_4_reference_images",
    ),
    ModelEntry(
        id=CF_FLUX_1_SCHNELL, alias="cf/flux-schnell", name="FLUX.1-schnell (Cloudflare)",
        upstream_id="@cf/black-forest-labs/flux-1-schnell",
        hint="Fast image", provider="cloudflare",
        scores=ModelScores(coding=0, reasoning=0, planning=0, tool_use=0, instruction=35, design=82),
        cost=ModelCost(0.00, 0.00, pricing_unit="per_image", unit_price=0.00), context_window=0, speed_tier="fast",
        capabilities=ModelCapabilities(can_generate_images=True, max_output_tokens=0),
        release_date="2024-12-01", family="flux",
        availability="workers_free_plan_10k_neurons_per_day; list_price_from_cloudflare_models_api_2026-10-09",
    ),
    ModelEntry(
        id=CF_SD_XL_LIGHTNING, alias="cf/sdxl", name="SD XL Lightning (Cloudflare)",
        upstream_id="@cf/bytedance/stable-diffusion-xl-lightning",
        hint="4-step fast", provider="cloudflare",
        scores=ModelScores(coding=0, reasoning=0, planning=0, tool_use=0, instruction=30, design=75),
        cost=ModelCost(0.00, 0.00, pricing_unit="per_image", unit_price=0.00), context_window=0, speed_tier="fast",
        capabilities=ModelCapabilities(can_generate_images=True, max_output_tokens=0),
        release_date="2024-06-01", family="stable-diffusion",
        availability="workers_free_plan_10k_neurons_per_day; list_price_from_cloudflare_models_api_2026-10-09",
    ),
    ModelEntry(
        id=CF_LEONARDO_PHOENIX, alias="cf/phoenix", name="Leonardo Phoenix (Cloudflare)",
        upstream_id="@cf/leonardo/phoenix-1.0",
        hint="Text render", provider="cloudflare",
        scores=ModelScores(coding=0, reasoning=0, planning=0, tool_use=0, instruction=40, design=85),
        cost=ModelCost(0.00, 0.00, pricing_unit="per_image", unit_price=0.00), context_window=0, speed_tier="medium",
        capabilities=ModelCapabilities(can_generate_images=True, max_output_tokens=0),
        release_date="2025-01-01", family="leonardo",
        availability="workers_free_plan_10k_neurons_per_day; list_price_from_cloudflare_models_api_2026-10-09; list_0.00583_per_512_tile_plus_0.00011_per_step",
    ),
    ModelEntry(
        id=CF_LEONARDO_LUCID, alias="cf/lucid", name="Leonardo Lucid Origin (Cloudflare)",
        upstream_id="@cf/leonardo/lucid-origin",
        hint="Design", provider="cloudflare",
        scores=ModelScores(coding=0, reasoning=0, planning=0, tool_use=0, instruction=38, design=83),
        cost=ModelCost(0.00, 0.00, pricing_unit="per_image", unit_price=0.00), context_window=0, speed_tier="medium",
        capabilities=ModelCapabilities(can_generate_images=True, max_output_tokens=0),
        release_date="2025-01-01", family="leonardo",
        availability="workers_free_plan_10k_neurons_per_day; list_price_from_cloudflare_models_api_2026-10-09; list_0.007_per_512_tile_plus_0.000132_per_step",
    ),
]

# Fallback used only when a model id is not registered in MODEL_CATALOG. Picked
# so under-provisioning (truncated plans) is preferred over silent over-cap
# rejection — current API ceilings for our completion models sit between 16k
# and 128k. Adapters resolve via _MODEL_MAX_OUTPUT_TOKENS first.
_MAX_OUTPUT_TOKENS_FALLBACK = 32_768


_MODEL_MAX_OUTPUT_TOKENS: dict[str, int] = {
    entry.id: entry.capabilities.max_output_tokens
    for entry in MODEL_CATALOG
    if entry.capabilities.max_output_tokens > 0
}


def get_max_output_tokens(model_id: str) -> int:
    """Return the catalog's max_output_tokens for a model id, or the fallback.

    Used by adapters whose upstream API requires an explicit max_tokens (notably
    the Anthropic Messages API). Adapters where the provider treats max_tokens
    as optional should not call this — they should send no cap and let the
    provider use its native default.
    """
    return _MODEL_MAX_OUTPUT_TOKENS.get(model_id, _MAX_OUTPUT_TOKENS_FALLBACK)

# Official contract verified 2026-09-19: https://docs.typesafe.ai/models.
# Zero scores mean unrated for the generative benchmark axes, not measured accuracy.
MODEL_CATALOG.append(ModelEntry(
    id="jev-1.13.0", alias="jev-1.13", name="Jev 1.13 · typed judgments",
    hint="Text-only typed classification; no chat or tools. Generative scores are unrated. $0.042/M input, free output.",
    provider="typesafe", scores=ModelScores(0, 0, 0, 0, 0, 0),
    cost=ModelCost(input_per_m=0.042, output_per_m=0), context_window=64000,
    speed_tier="fast", capabilities=ModelCapabilities(supports_chat=False,
        supports_typed_judgment=True, max_state_question_tokens=32000, max_output_tokens=0),
    family="jev", availability="Typed System One API; not a generative chat model",
))
