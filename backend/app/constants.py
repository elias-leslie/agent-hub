"""Shared constants used across the application."""

from __future__ import annotations

from dataclasses import dataclass, field

# Valid agent types supported by the platform
VALID_AGENT_TYPES = {"claude", "gemini", "openrouter", "openai", "xai", "zhipu", "minimax"}

# =============================================================================
# Valid Project IDs — mirrors SummitFlow projects table + utility scopes
# =============================================================================
# Update when new projects are registered in SummitFlow.
# Any project_id not in this set is rejected at session creation time.
VALID_PROJECT_IDS: frozenset[str] = frozenset({
    # Real projects (from SummitFlow projects table, each has root_path)
    "summitflow",
    "agent-hub",
    "portfolio-ai",
    "terminal",
    "monkey-fight",
    # Utility scopes (CLI, internal services — no root_path)
    "st-cli",
    "claude-consultation",
    "consult",
    "agent-playground",
})


# =============================================================================
# Model Constants - SINGLE SOURCE OF TRUTH
# =============================================================================
# Update these when new model versions are released.
# All code should import from here, not hardcode model strings.

# Claude models (Anthropic)
CLAUDE_SONNET = "claude-sonnet-4-5"
CLAUDE_OPUS = "claude-opus-4-6"
CLAUDE_HAIKU = "claude-haiku-4-5"

# Gemini 3 models (Google)
GEMINI_FLASH = "gemini-3-flash-preview"
GEMINI_PRO = "gemini-3-pro-preview"
GEMINI_IMAGE = "gemini-3-pro-image-preview"

# New experimental models
GEMINI_2_5_FLASH_LITE = "gemini-2.5-flash-lite"

# OpenRouter Models (Canonical IDs) — only models cheaper/exclusive on OR
OR_KIMI_K2_5 = "openrouter/moonshotai/kimi-k2.5"
OR_FREE_TRINITY = "openrouter/arcee-ai/trinity-large-preview:free"
OR_FREE_GLM = "openrouter/z-ai/glm-4.5-air:free"

# OpenAI models (Direct)
OPENAI_GPT_5_2 = "openai/gpt-5.2"
OPENAI_GPT_5_3_CODEX = "openai/gpt-5.3-codex"
OPENAI_GPT_NANO = "openai/gpt-5-nano"

# xAI models (Direct)
XAI_GROK_CODE_FAST = "xai/grok-code-fast-1"
XAI_GROK_4_1_FAST = "xai/grok-4.1-fast"

# Zhipu models (Direct)
ZHIPU_GLM_5 = "zhipu/glm-5"
ZHIPU_GLM_4_7 = "zhipu/glm-4.7"

# MiniMax models (Direct)
MINIMAX_M2_5 = "minimax/MiniMax-M2.5"


# =============================================================================
# Model Catalog Dataclasses
# =============================================================================

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


@dataclass(frozen=True)
class ModelCapabilities:
    """Model output and input capabilities."""

    can_generate_images: bool = False
    has_vision: bool = False
    can_edit_images: bool = False


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
    capabilities: ModelCapabilities = field(default_factory=ModelCapabilities)


# =============================================================================
# Model Catalog - ADD NEW MODELS HERE
# =============================================================================
# Single place to register UI-visible models. Everything else derives from this.
# Internal-only models (GEMINI_IMAGE, etc.) are NOT in the catalog.
# Scores sourced from SWE-Bench, GPQA Diamond, BFCL, IFEval, MMMU-Pro, etc.

MODEL_CATALOG: list[ModelEntry] = [
    # --- Claude (3) ---
    ModelEntry(
        id=CLAUDE_SONNET, alias="sonnet", name="Claude Sonnet 4.5",
        hint="Balanced", provider="claude",
        scores=ModelScores(coding=77, reasoning=83, planning=65, tool_use=72, instruction=82, design=68),
        cost=ModelCost(3.00, 15.00), context_window=1_000_000, speed_tier="medium",
        capabilities=ModelCapabilities(has_vision=True),
    ),
    ModelEntry(
        id=CLAUDE_OPUS, alias="opus", name="Claude Opus 4.6",
        hint="Powerful", provider="claude",
        scores=ModelScores(coding=80, reasoning=91, planning=70, tool_use=75, instruction=85, design=70),
        cost=ModelCost(5.00, 25.00), context_window=1_000_000, speed_tier="slow",
        capabilities=ModelCapabilities(has_vision=True),
    ),
    ModelEntry(
        id=CLAUDE_HAIKU, alias="haiku", name="Claude Haiku 4.5",
        hint="Quick", provider="claude",
        scores=ModelScores(coding=73, reasoning=70, planning=50, tool_use=65, instruction=65, design=60),
        cost=ModelCost(1.00, 5.00), context_window=200_000, speed_tier="fast",
        capabilities=ModelCapabilities(has_vision=True),
    ),
    # --- Gemini (3) ---
    ModelEntry(
        id=GEMINI_FLASH, alias="flash", name="Gemini 3 Flash",
        hint="Fast", provider="gemini",
        scores=ModelScores(coding=78, reasoning=90, planning=72, tool_use=75, instruction=83, design=85),
        cost=ModelCost(0.50, 3.00), context_window=1_000_000, speed_tier="fast",
        capabilities=ModelCapabilities(can_generate_images=True, has_vision=True, can_edit_images=True),
    ),
    ModelEntry(
        id=GEMINI_2_5_FLASH_LITE, alias="flash-lite", name="Gemini 2.5 Flash Lite",
        hint="Cheap", provider="gemini",
        scores=ModelScores(coding=34, reasoning=50, planning=40, tool_use=45, instruction=84, design=55),
        cost=ModelCost(0.10, 0.40), context_window=1_000_000, speed_tier="fast",
        capabilities=ModelCapabilities(has_vision=True),
    ),
    ModelEntry(
        id=GEMINI_PRO, alias="pro", name="Gemini 3 Pro",
        hint="Reasoning", provider="gemini",
        scores=ModelScores(coding=76, reasoning=92, planning=75, tool_use=78, instruction=85, design=88),
        cost=ModelCost(3.00, 15.00), context_window=1_000_000, speed_tier="medium",
        capabilities=ModelCapabilities(can_generate_images=True, has_vision=True, can_edit_images=True),
    ),
    # --- OpenRouter (3) — cheaper/exclusive on OR ---
    ModelEntry(
        id=OR_KIMI_K2_5, alias="or/kimi", name="Kimi K2.5 (OR)",
        hint="Kimi K2.5", provider="openrouter",
        scores=ModelScores(coding=75, reasoning=88, planning=72, tool_use=80, instruction=83, design=82),
        cost=ModelCost(0.50, 2.00), context_window=200_000, speed_tier="medium",
        capabilities=ModelCapabilities(has_vision=True),
    ),
    ModelEntry(
        id=OR_FREE_TRINITY, alias="or/free-trinity", name="Trinity Large (Free)",
        hint="Trinity Free", provider="openrouter",
        scores=ModelScores(coding=55, reasoning=60, planning=45, tool_use=50, instruction=65, design=45),
        cost=ModelCost(0.00, 0.00), context_window=128_000, speed_tier="fast",
    ),
    ModelEntry(
        id=OR_FREE_GLM, alias="or/free-glm", name="GLM-4.5 Air (Free)",
        hint="GLM Free", provider="openrouter",
        scores=ModelScores(coding=60, reasoning=65, planning=50, tool_use=55, instruction=70, design=50),
        cost=ModelCost(0.00, 0.00), context_window=128_000, speed_tier="fast",
        capabilities=ModelCapabilities(has_vision=True),
    ),
    # --- OpenAI (3) ---
    ModelEntry(
        id=OPENAI_GPT_5_2, alias="gpt5.2", name="GPT-5.2",
        hint="GPT 5.2", provider="openai",
        scores=ModelScores(coding=80, reasoning=93, planning=75, tool_use=76, instruction=87, design=70),
        cost=ModelCost(2.00, 10.00), context_window=400_000, speed_tier="medium",
        capabilities=ModelCapabilities(has_vision=True),
    ),
    ModelEntry(
        id=OPENAI_GPT_5_3_CODEX, alias="codex", name="GPT-5.3 Codex",
        hint="Codex", provider="openai",
        scores=ModelScores(coding=93, reasoning=92, planning=77, tool_use=78, instruction=88, design=72),
        cost=ModelCost(2.00, 14.00), context_window=400_000, speed_tier="fast",
        capabilities=ModelCapabilities(has_vision=True),
    ),
    ModelEntry(
        id=OPENAI_GPT_NANO, alias="nano", name="GPT-5 Nano",
        hint="Nano", provider="openai",
        scores=ModelScores(coding=40, reasoning=60, planning=35, tool_use=40, instruction=70, design=50),
        cost=ModelCost(0.05, 0.40), context_window=400_000, speed_tier="fast",
        capabilities=ModelCapabilities(has_vision=True),
    ),
    # --- xAI (2) ---
    ModelEntry(
        id=XAI_GROK_CODE_FAST, alias="grok", name="Grok Code Fast 1",
        hint="Grok Code", provider="xai",
        scores=ModelScores(coding=71, reasoning=65, planning=60, tool_use=68, instruction=76, design=65),
        cost=ModelCost(0.20, 0.50), context_window=2_000_000, speed_tier="fast",
        capabilities=ModelCapabilities(has_vision=True),
    ),
    ModelEntry(
        id=XAI_GROK_4_1_FAST, alias="grok-fast", name="Grok 4.1 Fast",
        hint="Grok 4.1", provider="xai",
        scores=ModelScores(coding=68, reasoning=75, planning=82, tool_use=80, instruction=78, design=65),
        cost=ModelCost(0.20, 0.50), context_window=2_000_000, speed_tier="fast",
        capabilities=ModelCapabilities(has_vision=True),
    ),
    # --- Zhipu (2) ---
    ModelEntry(
        id=ZHIPU_GLM_5, alias="glm5", name="GLM-5",
        hint="GLM-5", provider="zhipu",
        scores=ModelScores(coding=78, reasoning=92, planning=70, tool_use=75, instruction=85, design=68),
        cost=ModelCost(0.90, 2.88), context_window=200_000, speed_tier="medium",
        capabilities=ModelCapabilities(has_vision=True),
    ),
    ModelEntry(
        id=ZHIPU_GLM_4_7, alias="glm4.7", name="GLM-4.7",
        hint="GLM-4.7", provider="zhipu",
        scores=ModelScores(coding=74, reasoning=95, planning=67, tool_use=85, instruction=82, design=70),
        cost=ModelCost(0.35, 1.55), context_window=200_000, speed_tier="medium",
        capabilities=ModelCapabilities(has_vision=True),
    ),
    # --- MiniMax (1) ---
    ModelEntry(
        id=MINIMAX_M2_5, alias="minimax", name="MiniMax M2.5",
        hint="Coding", provider="minimax",
        scores=ModelScores(coding=80, reasoning=85, planning=76, tool_use=77, instruction=84, design=72),
        cost=ModelCost(0.15, 1.20), context_window=200_000, speed_tier="fast",
        capabilities=ModelCapabilities(has_vision=True),
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


# Default models for each use case
DEFAULT_CLAUDE_MODEL = CLAUDE_SONNET
DEFAULT_GEMINI_MODEL = GEMINI_FLASH

# Model for complex reasoning (code review, architecture decisions)
REASONING_CLAUDE_MODEL = CLAUDE_OPUS
REASONING_GEMINI_MODEL = GEMINI_PRO

# Model for fast/cheap operations (extraction, validation, summarization)
FAST_CLAUDE_MODEL = CLAUDE_HAIKU
FAST_GEMINI_MODEL = GEMINI_FLASH


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

# Model tier mappings for fallback routing
CLAUDE_TO_GEMINI_MAP = {
    CLAUDE_HAIKU: GEMINI_FLASH,
    CLAUDE_SONNET: GEMINI_FLASH,
    CLAUDE_OPUS: GEMINI_PRO,
}

GEMINI_TO_CLAUDE_MAP = {
    GEMINI_FLASH: CLAUDE_SONNET,
    GEMINI_PRO: CLAUDE_OPUS,
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

# =============================================================================
# Model Output Capabilities - Per Model Family
# NOTE: max_tokens constants removed - models auto-determine output length
# No artificial caps imposed by Agent Hub
