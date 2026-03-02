"""Model catalog with scores, costs, and capabilities."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.constants.models import (
    CC_CLAUDE_OPUS,
    CC_CLAUDE_SONNET,
    CLAUDE_HAIKU,
    CLAUDE_OPUS,
    CLAUDE_SONNET,
    GEMINI_2_5_FLASH_LITE,
    GEMINI_3_1_PRO,
    GEMINI_FLASH,
    GEMINI_IMAGE,
    GEMINI_IMAGE_NANO,
    GEMINI_IMAGE_NANO2,
    GEMINI_PRO,
    MINIMAX_IMAGE_01,
    MINIMAX_M2_5,
    NVIDIA_FLUX_1_DEV,
    NVIDIA_FLUX_1_KONTEXT,
    NVIDIA_FLUX_1_SCHNELL,
    NVIDIA_KIMI_K2_5,
    NVIDIA_MINIMAX_M2_5,
    NVIDIA_QWEN_3_5,
    NVIDIA_SD_3_5_LARGE,
    OPENAI_GPT_5_2,
    OPENAI_GPT_5_3_CODEX,
    OPENAI_GPT_NANO,
    OR_FREE_GLM,
    OR_FREE_TRINITY,
    OR_KIMI_K2_5,
    XAI_GROK_4_1_FAST,
    XAI_GROK_CODE_FAST,
    ZHIPU_GLM_4_7,
    ZHIPU_GLM_5,
)

# Scoring category weights for composite calculation
SCORE_WEIGHTS = {
    "coding": 0.25,
    "reasoning": 0.20,
    "planning": 0.15,
    "tool_use": 0.15,
    "instruction": 0.15,
    "design": 0.10,
}


@dataclass(frozen=True)
class ModelScores:
    """Benchmark scores normalized to 0-100 scale."""

    coding: int  # SWE-Bench Verified, HumanEval+, LiveCodeBench
    reasoning: int  # GPQA Diamond, MATH-500, ARC-AGI
    planning: int  # MEWC, BrowseComp, agentic evals
    tool_use: int  # BFCL, function calling accuracy
    instruction: int  # IFEval, MT-Bench, AlpacaEval
    design: int  # DesignBench, Design2Code, MMMU-Pro

    @property
    def composite(self) -> float:
        """Weighted average across all categories."""
        return round(
            self.coding * SCORE_WEIGHTS["coding"]
            + self.reasoning * SCORE_WEIGHTS["reasoning"]
            + self.planning * SCORE_WEIGHTS["planning"]
            + self.tool_use * SCORE_WEIGHTS["tool_use"]
            + self.instruction * SCORE_WEIGHTS["instruction"]
            + self.design * SCORE_WEIGHTS["design"],
            1,
        )


@dataclass(frozen=True)
class ModelCost:
    """Pricing in USD per million tokens."""

    input_per_m: float
    output_per_m: float
    # Service tier cost multipliers (e.g. OpenAI flex/priority tiers)
    service_tiers: dict[str, float] = field(default_factory=lambda: {"default": 1.0})
    # Prompt caching pricing (Anthropic)
    cache_read_per_million: float | None = None
    cache_write_per_million: float | None = None


@dataclass(frozen=True)
class ModelCapabilities:
    """Model output and input capabilities."""

    can_generate_images: bool = False
    has_vision: bool = False
    can_edit_images: bool = False
    has_thinking: bool = False
    supports_pdf: bool = False
    supports_audio: bool = False
    max_output_tokens: int = 8192


SPEED_TIER_TIMEOUT: dict[str, float] = {"fast": 30.0, "medium": 60.0, "slow": 120.0}


@dataclass(frozen=True)
class ModelEntry:
    """Rich model registry entry with scores, costs, and capabilities."""

    id: str
    alias: str
    name: str
    hint: str
    provider: str
    scores: ModelScores
    cost: ModelCost
    context_window: int
    speed_tier: str  # "fast", "medium", "slow"
    timeout_hint_seconds: float = 60.0
    capabilities: ModelCapabilities = field(default_factory=ModelCapabilities)
    release_date: str | None = None
    knowledge_cutoff: str | None = None
    family: str | None = None


# Single place to register UI-visible models. Everything else derives from this.
# Scores sourced from SWE-Bench, GPQA Diamond, BFCL, IFEval, MMMU-Pro, etc.
MODEL_CATALOG: list[ModelEntry] = [
    # --- Claude (3) ---
    ModelEntry(
        id=CLAUDE_SONNET, alias="sonnet", name="Claude Sonnet 4.6",
        hint="Balanced", provider="claude",
        scores=ModelScores(coding=80, reasoning=87, planning=72, tool_use=78, instruction=84, design=72),
        cost=ModelCost(3.00, 15.00, cache_read_per_million=0.30, cache_write_per_million=3.75),
        context_window=1_000_000, speed_tier="medium", timeout_hint_seconds=60.0,
        capabilities=ModelCapabilities(has_vision=True, has_thinking=True, supports_pdf=True, max_output_tokens=16384),
        release_date="2026-01-29", knowledge_cutoff="2025-05-01", family="claude-sonnet",
    ),
    ModelEntry(
        id=CLAUDE_OPUS, alias="opus", name="Claude Opus 4.6",
        hint="Powerful", provider="claude",
        scores=ModelScores(coding=80, reasoning=91, planning=70, tool_use=75, instruction=85, design=70),
        cost=ModelCost(5.00, 25.00, cache_read_per_million=0.50, cache_write_per_million=6.25),
        context_window=1_000_000, speed_tier="slow", timeout_hint_seconds=120.0,
        capabilities=ModelCapabilities(has_vision=True, has_thinking=True, supports_pdf=True, max_output_tokens=32768),
        release_date="2026-01-29", knowledge_cutoff="2025-05-01", family="claude-opus",
    ),
    ModelEntry(
        id=CLAUDE_HAIKU, alias="haiku", name="Claude Haiku 4.5",
        hint="Quick", provider="claude",
        scores=ModelScores(coding=73, reasoning=70, planning=50, tool_use=65, instruction=65, design=60),
        cost=ModelCost(1.00, 5.00, cache_read_per_million=0.10, cache_write_per_million=1.25),
        context_window=200_000, speed_tier="fast", timeout_hint_seconds=30.0,
        capabilities=ModelCapabilities(has_vision=True, supports_pdf=True, max_output_tokens=8192),
        release_date="2025-10-01", knowledge_cutoff="2025-04-01", family="claude-haiku",
    ),
    # --- Gemini (3) ---
    ModelEntry(
        id=GEMINI_FLASH, alias="flash", name="Gemini 3 Flash",
        hint="Fast", provider="gemini",
        scores=ModelScores(coding=78, reasoning=90, planning=72, tool_use=75, instruction=83, design=85),
        cost=ModelCost(0.50, 3.00), context_window=1_000_000, speed_tier="fast", timeout_hint_seconds=30.0,
        capabilities=ModelCapabilities(can_generate_images=True, has_vision=True, can_edit_images=True, has_thinking=True, supports_pdf=True, supports_audio=True, max_output_tokens=65536),
        release_date="2025-12-11", knowledge_cutoff="2025-09-01", family="gemini-flash",
    ),
    ModelEntry(
        id=GEMINI_2_5_FLASH_LITE, alias="flash-lite", name="Gemini 2.5 Flash Lite",
        hint="Cheap", provider="gemini",
        scores=ModelScores(coding=34, reasoning=50, planning=40, tool_use=45, instruction=84, design=55),
        cost=ModelCost(0.10, 0.40), context_window=1_000_000, speed_tier="fast", timeout_hint_seconds=30.0,
        capabilities=ModelCapabilities(has_vision=True, supports_pdf=True, max_output_tokens=8192),
        release_date="2025-06-01", knowledge_cutoff="2025-01-01", family="gemini-flash-lite",
    ),
    ModelEntry(
        id=GEMINI_PRO, alias="pro", name="Gemini 3 Pro",
        hint="Reasoning", provider="gemini",
        scores=ModelScores(coding=76, reasoning=92, planning=75, tool_use=78, instruction=85, design=88),
        cost=ModelCost(3.00, 15.00), context_window=1_000_000, speed_tier="medium", timeout_hint_seconds=60.0,
        capabilities=ModelCapabilities(can_generate_images=True, has_vision=True, can_edit_images=True, has_thinking=True, supports_pdf=True, supports_audio=True, max_output_tokens=65536),
        release_date="2025-12-11", knowledge_cutoff="2025-09-01", family="gemini-pro",
    ),
    ModelEntry(
        id=GEMINI_3_1_PRO, alias="3.1-pro", name="Gemini 3.1 Pro",
        hint="Deep Reasoning", provider="gemini",
        scores=ModelScores(coding=82, reasoning=96, planning=82, tool_use=82, instruction=88, design=90),
        cost=ModelCost(3.00, 15.00), context_window=1_000_000, speed_tier="slow", timeout_hint_seconds=120.0,
        capabilities=ModelCapabilities(has_vision=True, has_thinking=True, supports_pdf=True, supports_audio=True, max_output_tokens=65536),
        release_date="2026-02-01", knowledge_cutoff="2025-11-01", family="gemini-pro",
    ),
    # --- Gemini Image Models (3) ---
    ModelEntry(
        id=GEMINI_IMAGE, alias="pro-image", name="Gemini 3 Pro Image",
        hint="Image Gen", provider="gemini",
        scores=ModelScores(coding=20, reasoning=40, planning=30, tool_use=25, instruction=60, design=92),
        cost=ModelCost(3.00, 15.00), context_window=1_000_000, speed_tier="medium", timeout_hint_seconds=60.0,
        capabilities=ModelCapabilities(can_generate_images=True, has_vision=True, can_edit_images=True, max_output_tokens=8192),
        release_date="2025-12-11", family="gemini-image",
    ),
    ModelEntry(
        id=GEMINI_IMAGE_NANO, alias="nano-banana", name="Nano Banana",
        hint="Fast Image", provider="gemini",
        scores=ModelScores(coding=15, reasoning=30, planning=20, tool_use=20, instruction=50, design=80),
        cost=ModelCost(0.50, 3.00), context_window=1_000_000, speed_tier="fast", timeout_hint_seconds=30.0,
        capabilities=ModelCapabilities(can_generate_images=True, has_vision=True, can_edit_images=True, max_output_tokens=8192),
        release_date="2025-06-01", family="gemini-image",
    ),
    ModelEntry(
        id=GEMINI_IMAGE_NANO2, alias="nano-banana-2", name="Nano Banana 2",
        hint="Fastest Image", provider="gemini",
        scores=ModelScores(coding=15, reasoning=35, planning=22, tool_use=22, instruction=55, design=85),
        cost=ModelCost(0.50, 3.00), context_window=1_000_000, speed_tier="fast", timeout_hint_seconds=30.0,
        capabilities=ModelCapabilities(can_generate_images=True, has_vision=True, can_edit_images=True, max_output_tokens=8192),
        release_date="2026-02-01", family="gemini-image",
    ),
    # --- OpenRouter (3) — cheaper/exclusive on OR ---
    ModelEntry(
        id=OR_KIMI_K2_5, alias="or/kimi", name="Kimi K2.5 (OR)",
        hint="Kimi K2.5", provider="openrouter",
        scores=ModelScores(coding=75, reasoning=88, planning=72, tool_use=80, instruction=83, design=82),
        cost=ModelCost(0.50, 2.00), context_window=200_000, speed_tier="medium", timeout_hint_seconds=60.0,
        capabilities=ModelCapabilities(has_vision=True, has_thinking=True, max_output_tokens=16384),
        release_date="2025-12-01", family="kimi",
    ),
    ModelEntry(
        id=OR_FREE_TRINITY, alias="or/free-trinity", name="Trinity Large (Free)",
        hint="Trinity Free", provider="openrouter",
        scores=ModelScores(coding=55, reasoning=60, planning=45, tool_use=50, instruction=65, design=45),
        cost=ModelCost(0.00, 0.00), context_window=128_000, speed_tier="fast", timeout_hint_seconds=30.0,
        family="trinity",
    ),
    ModelEntry(
        id=OR_FREE_GLM, alias="or/free-glm", name="GLM-4.5 Air (Free)",
        hint="GLM Free", provider="openrouter",
        scores=ModelScores(coding=60, reasoning=65, planning=50, tool_use=55, instruction=70, design=50),
        cost=ModelCost(0.00, 0.00), context_window=128_000, speed_tier="fast", timeout_hint_seconds=30.0,
        capabilities=ModelCapabilities(has_vision=True),
        family="glm",
    ),
    # --- OpenAI (3) ---
    ModelEntry(
        id=OPENAI_GPT_5_2, alias="gpt5.2", name="GPT-5.2",
        hint="GPT 5.2", provider="openai",
        scores=ModelScores(coding=80, reasoning=93, planning=75, tool_use=76, instruction=87, design=70),
        cost=ModelCost(2.00, 10.00, service_tiers={"flex": 0.5, "default": 1.0, "priority": 2.0}),
        context_window=400_000, speed_tier="medium", timeout_hint_seconds=60.0,
        capabilities=ModelCapabilities(has_vision=True, has_thinking=True, supports_pdf=True, supports_audio=True, max_output_tokens=32768),
        release_date="2025-11-01", knowledge_cutoff="2025-06-01", family="gpt",
    ),
    ModelEntry(
        id=OPENAI_GPT_5_3_CODEX, alias="codex", name="GPT-5.3 Codex",
        hint="Codex", provider="openai",
        scores=ModelScores(coding=93, reasoning=92, planning=77, tool_use=78, instruction=88, design=72),
        cost=ModelCost(2.00, 14.00, service_tiers={"flex": 0.5, "default": 1.0, "priority": 2.0}),
        context_window=400_000, speed_tier="fast", timeout_hint_seconds=30.0,
        capabilities=ModelCapabilities(has_vision=True, has_thinking=True, max_output_tokens=32768),
        release_date="2026-01-15", knowledge_cutoff="2025-09-01", family="gpt-codex",
    ),
    ModelEntry(
        id=OPENAI_GPT_NANO, alias="nano", name="GPT-5 Nano",
        hint="Nano", provider="openai",
        scores=ModelScores(coding=40, reasoning=60, planning=35, tool_use=40, instruction=70, design=50),
        cost=ModelCost(0.05, 0.40, service_tiers={"flex": 0.5, "default": 1.0, "priority": 2.0}),
        context_window=400_000, speed_tier="fast", timeout_hint_seconds=30.0,
        capabilities=ModelCapabilities(has_vision=True, max_output_tokens=8192),
        release_date="2025-10-01", family="gpt-nano",
    ),
    # --- xAI (2) ---
    ModelEntry(
        id=XAI_GROK_CODE_FAST, alias="grok", name="Grok Code Fast 1",
        hint="Grok Code", provider="xai",
        scores=ModelScores(coding=71, reasoning=65, planning=60, tool_use=68, instruction=76, design=65),
        cost=ModelCost(0.20, 0.50), context_window=2_000_000, speed_tier="fast", timeout_hint_seconds=30.0,
        capabilities=ModelCapabilities(has_vision=True, max_output_tokens=16384),
        release_date="2025-11-01", family="grok",
    ),
    ModelEntry(
        id=XAI_GROK_4_1_FAST, alias="grok-fast", name="Grok 4.1 Fast",
        hint="Grok 4.1", provider="xai",
        scores=ModelScores(coding=68, reasoning=75, planning=82, tool_use=80, instruction=78, design=65),
        cost=ModelCost(0.20, 0.50), context_window=2_000_000, speed_tier="fast", timeout_hint_seconds=30.0,
        capabilities=ModelCapabilities(has_vision=True, has_thinking=True, max_output_tokens=16384),
        release_date="2026-01-01", family="grok",
    ),
    # --- Zhipu (2) ---
    ModelEntry(
        id=ZHIPU_GLM_5, alias="glm5", name="GLM-5",
        hint="GLM-5", provider="zhipu",
        scores=ModelScores(coding=78, reasoning=92, planning=70, tool_use=75, instruction=85, design=68),
        cost=ModelCost(0.90, 2.88), context_window=200_000, speed_tier="medium", timeout_hint_seconds=60.0,
        capabilities=ModelCapabilities(has_vision=True, has_thinking=True, max_output_tokens=16384),
        release_date="2025-10-01", family="glm",
    ),
    ModelEntry(
        id=ZHIPU_GLM_4_7, alias="glm4.7", name="GLM-4.7",
        hint="GLM-4.7", provider="zhipu",
        scores=ModelScores(coding=74, reasoning=95, planning=67, tool_use=85, instruction=82, design=70),
        cost=ModelCost(0.35, 1.55), context_window=200_000, speed_tier="medium", timeout_hint_seconds=60.0,
        capabilities=ModelCapabilities(has_vision=True, has_thinking=True, max_output_tokens=16384),
        release_date="2026-01-15", family="glm",
    ),
    # --- MiniMax (1) ---
    ModelEntry(
        id=MINIMAX_M2_5, alias="minimax", name="MiniMax M2.5",
        hint="Coding", provider="minimax",
        scores=ModelScores(coding=80, reasoning=85, planning=76, tool_use=77, instruction=84, design=60),
        cost=ModelCost(0.15, 1.20, cache_read_per_million=0.03),
        context_window=204_800, speed_tier="fast", timeout_hint_seconds=30.0,
        capabilities=ModelCapabilities(has_thinking=True, max_output_tokens=131_072),
        release_date="2026-02-12", knowledge_cutoff="2025-09-01", family="minimax",
    ),
    # --- NVIDIA NIM (3) — free tier via NVIDIA developer program ---
    ModelEntry(
        id=NVIDIA_QWEN_3_5, alias="nv/qwen", name="Qwen 3.5 397B (NVIDIA)",
        hint="Vision+Code", provider="nvidia",
        scores=ModelScores(coding=78, reasoning=90, planning=76, tool_use=73, instruction=77, design=85),
        cost=ModelCost(0.00, 0.00), context_window=262_144, speed_tier="medium", timeout_hint_seconds=60.0,
        capabilities=ModelCapabilities(has_vision=True, has_thinking=True, supports_pdf=True, max_output_tokens=32_768),
        release_date="2026-02-16", knowledge_cutoff="2025-09-01", family="qwen",
    ),
    ModelEntry(
        id=NVIDIA_MINIMAX_M2_5, alias="nv/minimax", name="MiniMax M2.5 (NVIDIA)",
        hint="Free Coding", provider="nvidia",
        scores=ModelScores(coding=80, reasoning=85, planning=76, tool_use=77, instruction=84, design=60),
        cost=ModelCost(0.00, 0.00), context_window=204_800, speed_tier="fast", timeout_hint_seconds=30.0,
        capabilities=ModelCapabilities(has_thinking=True, max_output_tokens=131_072),
        release_date="2026-02-12", knowledge_cutoff="2025-09-01", family="minimax",
    ),
    ModelEntry(
        id=NVIDIA_KIMI_K2_5, alias="nv/kimi", name="Kimi K2.5 (NVIDIA)",
        hint="Multimodal", provider="nvidia",
        scores=ModelScores(coding=79, reasoning=90, planning=78, tool_use=82, instruction=83, design=82),
        cost=ModelCost(0.00, 0.00), context_window=256_000, speed_tier="medium", timeout_hint_seconds=60.0,
        capabilities=ModelCapabilities(has_vision=True, has_thinking=True, max_output_tokens=32_768),
        release_date="2026-01-01", knowledge_cutoff="2025-09-01", family="kimi",
    ),
    # --- NVIDIA NIM Image Generation (3) — FLUX + Stable Diffusion via ai.api.nvidia.com ---
    ModelEntry(
        id=NVIDIA_FLUX_1_DEV, alias="nv/flux-dev", name="FLUX.1-dev (NVIDIA)",
        hint="Image Gen", provider="nvidia",
        scores=ModelScores(coding=0, reasoning=0, planning=0, tool_use=0, instruction=40, design=88),
        cost=ModelCost(0.00, 0.00), context_window=0, speed_tier="slow", timeout_hint_seconds=120.0,
        capabilities=ModelCapabilities(can_generate_images=True, max_output_tokens=0),
        release_date="2024-12-01", family="flux",
    ),
    ModelEntry(
        id=NVIDIA_FLUX_1_SCHNELL, alias="nv/flux-schnell", name="FLUX.1-schnell (NVIDIA)",
        hint="Fast Image", provider="nvidia",
        scores=ModelScores(coding=0, reasoning=0, planning=0, tool_use=0, instruction=35, design=82),
        cost=ModelCost(0.00, 0.00), context_window=0, speed_tier="fast", timeout_hint_seconds=30.0,
        capabilities=ModelCapabilities(can_generate_images=True, max_output_tokens=0),
        release_date="2024-12-01", family="flux",
    ),
    ModelEntry(
        id=NVIDIA_SD_3_5_LARGE, alias="nv/sd3.5", name="Stable Diffusion 3.5 Large (NVIDIA)",
        hint="Image Gen", provider="nvidia",
        scores=ModelScores(coding=0, reasoning=0, planning=0, tool_use=0, instruction=38, design=85),
        cost=ModelCost(0.00, 0.00), context_window=0, speed_tier="medium", timeout_hint_seconds=90.0,
        capabilities=ModelCapabilities(can_generate_images=True, max_output_tokens=0),
        release_date="2024-10-01", family="stable-diffusion",
    ),
    ModelEntry(
        id=NVIDIA_FLUX_1_KONTEXT, alias="nv/flux-kontext", name="FLUX.1-Kontext (NVIDIA)",
        hint="Image Edit", provider="nvidia",
        scores=ModelScores(coding=0, reasoning=0, planning=0, tool_use=0, instruction=50, design=90),
        cost=ModelCost(0.00, 0.00), context_window=0, speed_tier="medium", timeout_hint_seconds=120.0,
        capabilities=ModelCapabilities(can_generate_images=True, can_edit_images=True, max_output_tokens=0),
        release_date="2025-06-01", family="flux",
    ),
    # --- MiniMax Image Generation (1) — image-01 via api.minimax.io ---
    ModelEntry(
        id=MINIMAX_IMAGE_01, alias="mm/image-01", name="MiniMax Image-01",
        hint="Image Gen", provider="minimax",
        scores=ModelScores(coding=0, reasoning=0, planning=0, tool_use=0, instruction=35, design=80),
        cost=ModelCost(0.0035 * 1000, 0.00), context_window=0, speed_tier="fast", timeout_hint_seconds=60.0,
        capabilities=ModelCapabilities(can_generate_images=True, max_output_tokens=0),
        release_date="2025-02-15", family="minimax-image",
    ),
    # --- CloudCode Claude (2) — Claude via Google CloudCode PA, zero-cost ---
    ModelEntry(
        id=CC_CLAUDE_SONNET, alias="cc/sonnet", name="Claude Sonnet 4.6 (CC)",
        hint="Free Sonnet", provider="cloudcode",
        scores=ModelScores(coding=80, reasoning=87, planning=72, tool_use=78, instruction=84, design=72),
        cost=ModelCost(0.00, 0.00), context_window=200_000, speed_tier="medium", timeout_hint_seconds=60.0,
        capabilities=ModelCapabilities(has_vision=True, has_thinking=True, supports_pdf=True, max_output_tokens=16384),
        release_date="2026-01-29", knowledge_cutoff="2025-05-01", family="claude-sonnet",
    ),
    ModelEntry(
        id=CC_CLAUDE_OPUS, alias="cc/opus", name="Claude Opus 4.6 Thinking (CC)",
        hint="Free Opus", provider="cloudcode",
        scores=ModelScores(coding=80, reasoning=91, planning=70, tool_use=75, instruction=85, design=70),
        cost=ModelCost(0.00, 0.00), context_window=200_000, speed_tier="slow", timeout_hint_seconds=120.0,
        capabilities=ModelCapabilities(has_vision=True, has_thinking=True, supports_pdf=True, max_output_tokens=32768),
        release_date="2026-01-29", knowledge_cutoff="2025-05-01", family="claude-opus",
    ),
]

# Backward-compat: flat dict list for code that imports MODEL_REGISTRY
MODEL_REGISTRY: list[dict[str, str]] = [
    {"id": e.id, "alias": e.alias, "name": e.name, "hint": e.hint, "provider": e.provider}
    for e in MODEL_CATALOG
]

# Lookup by model ID
MODEL_CATALOG_BY_ID: dict[str, ModelEntry] = {e.id: e for e in MODEL_CATALOG}

# Derived from catalog
MODEL_ALIASES: dict[str, str] = {e.alias: e.id for e in MODEL_CATALOG}


def resolve_model(alias: str) -> str:
    """Resolve model alias to canonical ID. Pass-through if not an alias."""
    return MODEL_ALIASES.get(alias.lower(), alias)


def _models_for_provider(provider: str) -> tuple[str, ...]:
    """Derive valid model IDs + aliases for a provider from the catalog."""
    return tuple(
        x
        for entry in MODEL_CATALOG
        if entry.provider == provider
        for x in (entry.id, entry.alias)
    )


# Valid model lists for validation (derived from registry)
VALID_CLAUDE_MODELS = _models_for_provider("claude")
VALID_GEMINI_MODELS = _models_for_provider("gemini")
VALID_OPENAI_MODELS = _models_for_provider("openai")
VALID_XAI_MODELS = _models_for_provider("xai")
VALID_ZHIPU_MODELS = _models_for_provider("zhipu")
VALID_MINIMAX_MODELS = _models_for_provider("minimax")
VALID_NVIDIA_MODELS = _models_for_provider("nvidia")
VALID_CLOUDCODE_MODELS = _models_for_provider("cloudcode")

# Model tier mappings for fallback routing
CLAUDE_TO_GEMINI_MAP = {
    CLAUDE_HAIKU: GEMINI_FLASH,
    CLAUDE_SONNET: GEMINI_FLASH,
    CLAUDE_OPUS: GEMINI_3_1_PRO,
}

GEMINI_TO_CLAUDE_MAP = {
    GEMINI_FLASH: CLAUDE_SONNET,
    GEMINI_PRO: CLAUDE_OPUS,
    GEMINI_3_1_PRO: CLAUDE_OPUS,
    GEMINI_2_5_FLASH_LITE: CLAUDE_HAIKU,
}

# Cross-provider fallback maps (new providers → Claude)
OPENAI_TO_CLAUDE_MAP = {
    OPENAI_GPT_NANO: CLAUDE_HAIKU,
    OPENAI_GPT_5_2: CLAUDE_SONNET,
    OPENAI_GPT_5_3_CODEX: CLAUDE_OPUS,
}

XAI_TO_CLAUDE_MAP = {
    XAI_GROK_CODE_FAST: CLAUDE_SONNET,
    XAI_GROK_4_1_FAST: CLAUDE_OPUS,
}

ZHIPU_TO_CLAUDE_MAP = {
    ZHIPU_GLM_5: CLAUDE_SONNET,
    ZHIPU_GLM_4_7: CLAUDE_SONNET,
}

MINIMAX_TO_CLAUDE_MAP = {
    MINIMAX_M2_5: CLAUDE_SONNET,
}

NVIDIA_TO_CLAUDE_MAP = {
    NVIDIA_QWEN_3_5: CLAUDE_SONNET,
    NVIDIA_MINIMAX_M2_5: CLAUDE_SONNET,
    NVIDIA_KIMI_K2_5: CLAUDE_SONNET,
}

CLOUDCODE_TO_CLAUDE_MAP = {
    CC_CLAUDE_SONNET: CLAUDE_SONNET,
    CC_CLAUDE_OPUS: CLAUDE_OPUS,
}


def get_timeout_for_model(model_id: str, explicit: float | None = None) -> float:
    """Resolve effective timeout: explicit > catalog hint > 300s default."""
    if explicit is not None:
        return explicit
    entry = MODEL_CATALOG_BY_ID.get(model_id)
    if entry:
        return entry.timeout_hint_seconds
    return 300.0
