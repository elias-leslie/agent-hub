"""Shared constants used across the application."""

# Valid agent types supported by the platform
VALID_AGENT_TYPES = {"claude", "gemini", "openrouter", "openai", "xai", "zhipu"}


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
OR_MINIMAX_2_1 = "openrouter/minimax/minimax-m2.1"
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

# =============================================================================
# Model Registry - ADD NEW MODELS HERE
# =============================================================================
# Single place to register UI-visible models. Everything else derives from this.
# Internal-only models (GEMINI_IMAGE, etc.) are NOT in the registry.

MODEL_REGISTRY: list[dict[str, str]] = [
    # --- Claude (3) ---
    {
        "id": CLAUDE_SONNET,
        "alias": "sonnet",
        "name": "Claude Sonnet 4.5",
        "hint": "Balanced",
        "provider": "claude",
    },
    {
        "id": CLAUDE_OPUS,
        "alias": "opus",
        "name": "Claude Opus 4.6",
        "hint": "Powerful",
        "provider": "claude",
    },
    {
        "id": CLAUDE_HAIKU,
        "alias": "haiku",
        "name": "Claude Haiku 4.5",
        "hint": "Quick",
        "provider": "claude",
    },
    # --- Gemini (3) ---
    {
        "id": GEMINI_FLASH,
        "alias": "flash",
        "name": "Gemini 3 Flash",
        "hint": "Fast",
        "provider": "gemini",
    },
    {
        "id": GEMINI_2_5_FLASH_LITE,
        "alias": "flash-lite",
        "name": "Gemini 2.5 Flash Lite",
        "hint": "Cheap",
        "provider": "gemini",
    },
    {
        "id": GEMINI_PRO,
        "alias": "pro",
        "name": "Gemini 3 Pro",
        "hint": "Reasoning",
        "provider": "gemini",
    },
    # --- OpenRouter (4) — cheaper/exclusive on OR ---
    {
        "id": OR_KIMI_K2_5,
        "alias": "or/kimi",
        "name": "Kimi K2.5 (OR)",
        "hint": "Kimi K2.5",
        "provider": "openrouter",
    },
    {
        "id": OR_MINIMAX_2_1,
        "alias": "or/minimax",
        "name": "MiniMax 2.1 (OR)",
        "hint": "MiniMax",
        "provider": "openrouter",
    },
    {
        "id": OR_FREE_TRINITY,
        "alias": "or/free-trinity",
        "name": "Trinity Large (Free)",
        "hint": "Trinity Free",
        "provider": "openrouter",
    },
    {
        "id": OR_FREE_GLM,
        "alias": "or/free-glm",
        "name": "GLM-4.5 Air (Free)",
        "hint": "GLM Free",
        "provider": "openrouter",
    },
    # --- OpenAI (3) ---
    {
        "id": OPENAI_GPT_5_2,
        "alias": "gpt5.2",
        "name": "GPT-5.2",
        "hint": "GPT 5.2",
        "provider": "openai",
    },
    {
        "id": OPENAI_GPT_5_3_CODEX,
        "alias": "codex",
        "name": "GPT-5.3 Codex",
        "hint": "Codex",
        "provider": "openai",
    },
    {
        "id": OPENAI_GPT_NANO,
        "alias": "nano",
        "name": "GPT-5 Nano",
        "hint": "Nano",
        "provider": "openai",
    },
    # --- xAI (2) ---
    {
        "id": XAI_GROK_CODE_FAST,
        "alias": "grok",
        "name": "Grok Code Fast 1",
        "hint": "Grok Code",
        "provider": "xai",
    },
    {
        "id": XAI_GROK_4_1_FAST,
        "alias": "grok-fast",
        "name": "Grok 4.1 Fast",
        "hint": "Grok 4.1",
        "provider": "xai",
    },
    # --- Zhipu (2) ---
    {
        "id": ZHIPU_GLM_5,
        "alias": "glm5",
        "name": "GLM-5",
        "hint": "GLM-5",
        "provider": "zhipu",
    },
    {
        "id": ZHIPU_GLM_4_7,
        "alias": "glm4.7",
        "name": "GLM-4.7",
        "hint": "GLM-4.7",
        "provider": "zhipu",
    },
]

# Derived from registry
MODEL_ALIASES: dict[str, str] = {entry["alias"]: entry["id"] for entry in MODEL_REGISTRY}


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
    """Derive valid model IDs + aliases for a provider from the registry."""
    return tuple(
        x
        for entry in MODEL_REGISTRY
        if entry["provider"] == provider
        for x in (entry["id"], entry["alias"])
    )


# Valid model lists for validation (derived from registry)
VALID_CLAUDE_MODELS = _models_for_provider("claude")
VALID_GEMINI_MODELS = _models_for_provider("gemini")
VALID_OPENAI_MODELS = _models_for_provider("openai")
VALID_XAI_MODELS = _models_for_provider("xai")
VALID_ZHIPU_MODELS = _models_for_provider("zhipu")

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

# =============================================================================
# Model Output Capabilities - Per Model Family
# NOTE: max_tokens constants removed - models auto-determine output length
# No artificial caps imposed by Agent Hub
