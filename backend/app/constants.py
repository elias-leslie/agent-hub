"""Shared constants used across the application."""

# Valid agent types supported by the platform
VALID_AGENT_TYPES = {"claude", "gemini"}


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

# OpenAI models (PLACEHOLDER - not implemented)
# These constants exist for future integration. Using them will raise NotImplementedError.
GPT_5_2_CODEX = "gpt-5.2-codex"
GPT_5 = "gpt-5"

# Model aliases (for convenience)
MODEL_ALIASES: dict[str, str] = {
    "sonnet": CLAUDE_SONNET,
    "opus": CLAUDE_OPUS,
    "haiku": CLAUDE_HAIKU,
    "flash": GEMINI_FLASH,
    "pro": GEMINI_PRO,
}


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

# Valid model lists for validation
VALID_CLAUDE_MODELS = (CLAUDE_SONNET, CLAUDE_OPUS, CLAUDE_HAIKU, "sonnet", "opus", "haiku")
VALID_GEMINI_MODELS = (GEMINI_FLASH, GEMINI_PRO, "flash", "pro")
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
}

# =============================================================================
# Model Output Limits - Used by token_counter for recommendations
# =============================================================================
DEFAULT_OUTPUT_LIMIT = 8192  # Default for general use case
OUTPUT_LIMIT_AGENTIC = 64000  # For agentic use cases with tool use
OUTPUT_LIMIT_ANALYSIS = 32768  # For analysis tasks
OUTPUT_LIMIT_CODE = 16384  # For code generation
OUTPUT_LIMIT_CHAT = 4096  # For chat/conversation

# Per-model output limits (base model name -> max output tokens)
# Keys must match MODEL_PRICING keys in token_counter.py
OUTPUT_LIMITS: dict[str, int] = {
    "claude-sonnet-4": 64000,
    "claude-opus-4": 64000,
    "claude-haiku-4": 64000,
    "gemini-3-flash": 65536,
    "gemini-3-pro": 65536,
}

# =============================================================================
# Model Output Capabilities - Per Model Family
# NOTE: The above constants are recommendations, not hard limits
# Models auto-determine actual output length up to their maximum
