"""Shared constants used across the application."""

# Valid agent types supported by the platform
VALID_AGENT_TYPES = {"claude", "gemini"}

# =============================================================================
# Model Constants - SINGLE SOURCE OF TRUTH
# =============================================================================
# Update these when new model versions are released.
# All code should import from here, not hardcode model strings.

# Claude 4.5 models (Anthropic) - short form
CLAUDE_SONNET = "claude-sonnet-4-5"
CLAUDE_OPUS = "claude-opus-4-5"
CLAUDE_HAIKU = "claude-haiku-4-5"

# Full model IDs with date suffix (for APIs that need them)
CLAUDE_SONNET_FULL = "claude-sonnet-4-5-20250514"
CLAUDE_OPUS_FULL = "claude-opus-4-5-20250514"
CLAUDE_HAIKU_FULL = "claude-haiku-4-5-20250514"

# Gemini 3 models (Google)
GEMINI_FLASH = "gemini-3-flash-preview"
GEMINI_PRO = "gemini-3-pro-preview"

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
VALID_CLAUDE_MODELS = (
    CLAUDE_SONNET,
    CLAUDE_OPUS,
    CLAUDE_HAIKU,
    CLAUDE_SONNET_FULL,
    CLAUDE_OPUS_FULL,
    CLAUDE_HAIKU_FULL,
    # Shorthand aliases
    "sonnet",
    "opus",
    "haiku",
)

VALID_GEMINI_MODELS = (
    GEMINI_FLASH,
    GEMINI_PRO,
)

# Model tier mappings for fallback routing
CLAUDE_TO_GEMINI_MAP = {
    CLAUDE_HAIKU: GEMINI_FLASH,
    CLAUDE_HAIKU_FULL: GEMINI_FLASH,
    CLAUDE_SONNET: GEMINI_FLASH,
    CLAUDE_SONNET_FULL: GEMINI_FLASH,
    CLAUDE_OPUS: GEMINI_PRO,
    CLAUDE_OPUS_FULL: GEMINI_PRO,
}

GEMINI_TO_CLAUDE_MAP = {
    GEMINI_FLASH: CLAUDE_SONNET_FULL,
    GEMINI_PRO: CLAUDE_OPUS_FULL,
}

# =============================================================================
# Model Aliases - Canonical Name Resolution
# =============================================================================
# Maps short/alias names to canonical model identifiers.
# Used by all endpoints to normalize model names before routing.

MODEL_ALIASES: dict[str, str] = {
    # Claude short forms
    "claude-sonnet-4-5": CLAUDE_SONNET_FULL,
    "claude-haiku-4-5": CLAUDE_HAIKU_FULL,
    "claude-opus-4-5": CLAUDE_OPUS_FULL,
    # Gemini short forms
    "gemini-3-flash": GEMINI_FLASH,
    "gemini-3-pro": GEMINI_PRO,
}


def resolve_model(model: str) -> str:
    """Resolve model alias to canonical name.

    Args:
        model: Model name (may be alias or canonical)

    Returns:
        Canonical model identifier
    """
    return MODEL_ALIASES.get(model, model)


# =============================================================================
# Output Token Limits - Per Model Family
# =============================================================================
# Max output tokens each model can generate. Used for defaults and validation.
# These use model base names (pattern matching) like CONTEXT_LIMITS in token_counter.

OUTPUT_LIMITS: dict[str, int] = {
    # Claude 4.5 family - 64K output (confirmed via Anthropic docs)
    "claude-opus-4": 64000,
    "claude-sonnet-4": 64000,
    "claude-haiku-4": 64000,
    # Gemini 3 family - 65K output (confirmed via Google Cloud docs)
    "gemini-3-flash": 65536,
    "gemini-3-pro": 65536,
}

# Default output limit when model is unknown (conservative - works for all models)
DEFAULT_OUTPUT_LIMIT = 8192

# =============================================================================
# Use-Case Specific Output Defaults
# =============================================================================
# Different use cases have different optimal max_tokens settings.
# These are recommendations, not hard limits.

OUTPUT_LIMIT_CHAT = 4096  # Short conversational responses
OUTPUT_LIMIT_CODE = 16384  # Code generation (functions, classes)
OUTPUT_LIMIT_ANALYSIS = 32768  # Long-form analysis, documentation
OUTPUT_LIMIT_AGENTIC = 64000  # Agentic workloads (tool use, multi-step)
