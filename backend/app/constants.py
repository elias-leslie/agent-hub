"""Shared constants used across the application."""

from enum import Enum

# Valid agent types supported by the platform
VALID_AGENT_TYPES = {"claude", "gemini"}


# =============================================================================
# Model Capabilities - Semantic Task Categories
# =============================================================================
# Use these to request a model by capability rather than specific model name.
# This allows routing logic to select the best model for the task.


class ModelCapability(str, Enum):
    """Capabilities that models can be selected for.

    DEPRECATED: Use agent slugs instead (e.g., "agent:coder" for CODING capability).
    This enum is maintained for backward compatibility during migration.

    Migration path:
    - CODING -> agent:coder
    - PLANNING -> agent:planner
    - REVIEW -> agent:reviewer
    - FAST_TASK -> agent:extractor
    - WORKER -> agent:fixer
    - SUPERVISOR_PRIMARY -> agent:supervisor
    - SUPERVISOR_AUDIT -> agent:auditor
    """

    # General purpose capabilities
    CODING = "coding"  # Code generation and modification
    PLANNING = "planning"  # Task planning and architecture
    REVIEW = "review"  # Code review and analysis
    FAST_TASK = "fast_task"  # Quick, cheap operations

    # Self-healing escalation levels
    WORKER = "worker"  # First-line error fixing (cheap, fast)
    SUPERVISOR_PRIMARY = "supervisor_primary"  # Complex fixes (Claude Sonnet)
    SUPERVISOR_AUDIT = "supervisor_audit"  # Audit fixes (Gemini Pro)


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


# =============================================================================
# Capability-to-Model Mapping
# =============================================================================
# Default model selection for each capability. Can be overridden via routing_config.

# Capability to Agent mapping (preferred over direct models)
# Use agent:slug format which routes to Agent Hub agents with mandate injection
CAPABILITY_TO_AGENT: dict[ModelCapability, str] = {
    ModelCapability.CODING: "agent:coder",
    ModelCapability.PLANNING: "agent:planner",
    ModelCapability.REVIEW: "agent:reviewer",
    ModelCapability.FAST_TASK: "agent:extractor",
    ModelCapability.WORKER: "agent:fixer",
    ModelCapability.SUPERVISOR_PRIMARY: "agent:supervisor",
    ModelCapability.SUPERVISOR_AUDIT: "agent:auditor",
}

# Legacy: Default models for each capability (fallback if agent not available)
DEFAULT_CAPABILITY_MODELS: dict[ModelCapability, str] = {
    # General purpose
    ModelCapability.CODING: CLAUDE_SONNET,
    ModelCapability.PLANNING: CLAUDE_SONNET,
    ModelCapability.REVIEW: CLAUDE_OPUS,
    ModelCapability.FAST_TASK: GEMINI_FLASH,
    # Self-healing escalation
    ModelCapability.WORKER: GEMINI_FLASH,
    ModelCapability.SUPERVISOR_PRIMARY: CLAUDE_SONNET,
    ModelCapability.SUPERVISOR_AUDIT: GEMINI_PRO,
}


def get_model_for_capability(
    capability: ModelCapability | str,
    provider_override: str | None = None,
    use_agents: bool = True,
) -> str:
    """Get the model/agent for a capability.

    DEPRECATED: Consider using agent slugs directly (e.g., "agent:coder").

    Args:
        capability: ModelCapability enum or string name
        provider_override: Force a specific provider ("claude" or "gemini")
        use_agents: If True, return agent:slug (default). If False, return raw model.

    Returns:
        Model ID string or agent:slug suitable for API calls

    Raises:
        ValueError: If capability is unknown
    """
    import warnings

    warnings.warn(
        "get_model_for_capability is deprecated. Use agent slugs directly "
        "(e.g., 'agent:coder' instead of ModelCapability.CODING).",
        DeprecationWarning,
        stacklevel=2,
    )

    if isinstance(capability, str):
        try:
            capability = ModelCapability(capability.lower())
        except ValueError as e:
            valid = ", ".join(c.value for c in ModelCapability)
            raise ValueError(f"Unknown capability: {capability}. Valid: {valid}") from e

    # Prefer agent-based routing (new approach)
    if use_agents and provider_override != "claude" and provider_override != "gemini":
        agent_slug = CAPABILITY_TO_AGENT.get(capability)
        if agent_slug:
            return agent_slug

    # Fallback to legacy model mapping
    model = DEFAULT_CAPABILITY_MODELS.get(capability)
    if model is None:
        raise ValueError(f"No model mapping for capability: {capability}")

    # Apply provider override if requested
    if provider_override == "claude" and model.startswith("gemini"):
        model = GEMINI_TO_CLAUDE_MAP.get(model, CLAUDE_SONNET)
    elif provider_override == "gemini" and model.startswith("claude"):
        model = CLAUDE_TO_GEMINI_MAP.get(model, GEMINI_FLASH)

    return model
