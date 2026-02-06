"""Shared constants used across the application."""

# Valid agent types supported by the platform
VALID_AGENT_TYPES = {"claude", "gemini", "openrouter"}


# =============================================================================
# Model Constants - SINGLE SOURCE OF TRUTH
# =============================================================================
# Update these when new model versions are released.
# All code should import from here, not hardcode model strings.

# Claude 4.5 models (Anthropic)
CLAUDE_SONNET = "claude-sonnet-4-5"
CLAUDE_OPUS = "claude-opus-4-5"
CLAUDE_HAIKU = "claude-haiku-4-5"

# Gemini 3 models (Google)
GEMINI_FLASH = "gemini-3-flash-preview"
GEMINI_PRO = "gemini-3-pro-preview"
GEMINI_IMAGE = "gemini-3-pro-image-preview"

# New experimental models
GEMINI_2_5_FLASH_LITE = "gemini-2.5-flash-lite"

# OpenRouter Models (Canonical IDs)
OR_GROK_CODE = "openrouter/x-ai/grok-code-fast-1"
OR_GROK_4_1 = "openrouter/x-ai/grok-4.1-fast"
OR_KIMI_K2_5 = "openrouter/moonshotai/kimi-k2.5"
OR_GEMINI_3_FLASH = "openrouter/google/gemini-3-flash-preview"
OR_GEMINI_3_PRO = "openrouter/google/gemini-3-pro-preview"
OR_MINIMAX_2_1 = "openrouter/minimax/minimax-m2.1"
OR_FREE_TRINITY = "openrouter/arcee-ai/trinity-large-preview:free"
OR_FREE_GLM = "openrouter/z-ai/glm-4.5-air:free"

# OpenAI models (PLACEHOLDER - not implemented)
# These constants exist for future integration. Using them will raise NotImplementedError.
GPT_5_2_CODEX = "gpt-5.2-codex"
GPT_5 = "gpt-5"

# =============================================================================
# Model Registry - ADD NEW MODELS HERE
# =============================================================================
# Single place to register UI-visible models. Everything else derives from this.
# Internal-only models (GEMINI_IMAGE, GPT_5, etc.) are NOT in the registry.

MODEL_REGISTRY: list[dict[str, str]] = [
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
        "name": "Claude Opus 4.5",
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
    {
        "id": OR_GROK_CODE,
        "alias": "or/grok",
        "name": "Grok Code Fast 1 (OR)",
        "hint": "Grok Code",
        "provider": "openrouter",
    },
    {
        "id": OR_GROK_4_1,
        "alias": "or/grok-fast",
        "name": "Grok 4.1 Fast (OR)",
        "hint": "Grok 4.1",
        "provider": "openrouter",
    },
    {
        "id": OR_KIMI_K2_5,
        "alias": "or/kimi",
        "name": "Kimi K2.5 (OR)",
        "hint": "Kimi K2.5",
        "provider": "openrouter",
    },
    {
        "id": OR_GEMINI_3_FLASH,
        "alias": "or/gemini-flash",
        "name": "Gemini 3 Flash (OR)",
        "hint": "OR Flash",
        "provider": "openrouter",
    },
    {
        "id": OR_GEMINI_3_PRO,
        "alias": "or/gemini-pro",
        "name": "Gemini 3 Pro (OR)",
        "hint": "OR Pro",
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

# Valid model lists for validation (derived from registry)
VALID_CLAUDE_MODELS = tuple(
    x
    for entry in MODEL_REGISTRY
    if entry["provider"] == "claude"
    for x in (entry["id"], entry["alias"])
)
VALID_GEMINI_MODELS = tuple(
    x
    for entry in MODEL_REGISTRY
    if entry["provider"] == "gemini"
    for x in (entry["id"], entry["alias"])
)
# OpenAI models - placeholder only, will raise NotImplementedError if used
VALID_OPENAI_MODELS = (GPT_5_2_CODEX, GPT_5, "gpt-5.2-codex", "gpt-5")

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

# =============================================================================
# Model Output Capabilities - Per Model Family
# NOTE: max_tokens constants removed - models auto-determine output length
# No artificial caps imposed by Agent Hub
