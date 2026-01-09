"""
Token counting and cost estimation service.

Uses tiktoken for accurate token counting before API calls.
"""

import logging
from dataclasses import dataclass

import tiktoken

logger = logging.getLogger(__name__)

# Model pricing per 1M tokens (as of 2025)
# Format: {model_pattern: {"input": price, "output": price, "cached_input": price}}
MODEL_PRICING: dict[str, dict[str, float]] = {
    # Claude models
    "claude-opus-4": {"input": 15.0, "output": 75.0, "cached_input": 1.5},
    "claude-sonnet-4": {"input": 3.0, "output": 15.0, "cached_input": 0.3},
    "claude-haiku-4": {"input": 0.25, "output": 1.25, "cached_input": 0.025},
    # Gemini 3 models
    "gemini-3-flash": {"input": 0.075, "output": 0.30, "cached_input": 0.0},
    "gemini-3-pro": {"input": 1.25, "output": 5.0, "cached_input": 0.0},
}

# Context window limits
CONTEXT_LIMITS: dict[str, int] = {
    "claude-opus-4": 200000,
    "claude-sonnet-4": 200000,
    "claude-haiku-4": 200000,
    "gemini-3-flash": 1000000,
    "gemini-3-pro": 2000000,
}

# Default context limit
DEFAULT_CONTEXT_LIMIT = 100000


@dataclass
class TokenEstimate:
    """Token and cost estimate for a request."""

    input_tokens: int
    estimated_output_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    context_limit: int
    context_usage_percent: float
    context_warning: str | None = None


@dataclass
class CostBreakdown:
    """Detailed cost breakdown."""

    input_cost_usd: float
    output_cost_usd: float
    cached_input_cost_usd: float
    total_cost_usd: float


def _get_model_base(model: str) -> str:
    """Extract model base name for pricing lookup."""
    model_lower = model.lower()
    for base in MODEL_PRICING:
        if base in model_lower:
            return base
    # Default to sonnet pricing
    return "claude-sonnet-4"


def _get_encoding() -> tiktoken.Encoding:
    """Get tiktoken encoding for Claude-like models."""
    # Claude uses a GPT-4-like tokenizer
    try:
        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        # Fallback to simpler encoding
        return tiktoken.get_encoding("gpt2")


def count_tokens(text: str) -> int:
    """
    Count tokens in text using tiktoken.

    Args:
        text: Text to count tokens for

    Returns:
        Number of tokens
    """
    encoding = _get_encoding()
    return len(encoding.encode(text))


def count_message_tokens(messages: list[dict[str, str]]) -> int:
    """
    Count tokens in a list of messages.

    Includes per-message overhead for role tokens.

    Args:
        messages: List of message dicts with "role" and "content"

    Returns:
        Total token count
    """
    encoding = _get_encoding()
    total = 0

    for message in messages:
        # Per-message overhead (~4 tokens for role + formatting)
        total += 4
        role = message.get("role", "")
        content = message.get("content", "")
        total += len(encoding.encode(role))
        total += len(encoding.encode(content))

    # Priming tokens at start
    total += 2
    return total


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    model: str,
    cached_input_tokens: int = 0,
) -> CostBreakdown:
    """
    Calculate cost for a request.

    Args:
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        model: Model identifier
        cached_input_tokens: Number of cached input tokens (Claude only)

    Returns:
        Cost breakdown in USD
    """
    base = _get_model_base(model)
    pricing = MODEL_PRICING.get(base, MODEL_PRICING["claude-sonnet-4"])

    # Calculate costs per million tokens
    uncached_input = input_tokens - cached_input_tokens
    input_cost = (uncached_input / 1_000_000) * pricing["input"]
    cached_cost = (cached_input_tokens / 1_000_000) * pricing["cached_input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]

    return CostBreakdown(
        input_cost_usd=input_cost,
        output_cost_usd=output_cost,
        cached_input_cost_usd=cached_cost,
        total_cost_usd=input_cost + cached_cost + output_cost,
    )


def estimate_request(
    messages: list[dict[str, str]],
    model: str,
    max_tokens: int = 8192,  # DEFAULT_OUTPUT_LIMIT from app.constants
) -> TokenEstimate:
    """
    Estimate tokens and cost for a request before sending.

    Args:
        messages: Request messages
        model: Model identifier
        max_tokens: Maximum tokens in response

    Returns:
        Token estimate with cost and context warnings
    """
    input_tokens = count_message_tokens(messages)

    # Estimate output as min(max_tokens, typical response)
    # Most responses are much shorter than max_tokens
    estimated_output = min(max_tokens, max(500, input_tokens // 2))

    total_tokens = input_tokens + estimated_output

    # Get context limit
    base = _get_model_base(model)
    context_limit = CONTEXT_LIMITS.get(base, DEFAULT_CONTEXT_LIMIT)
    context_usage = (input_tokens / context_limit) * 100

    # Check for context warnings
    warning = None
    if context_usage > 90:
        warning = f"CRITICAL: Input uses {context_usage:.1f}% of context limit"
    elif context_usage > 75:
        warning = f"WARNING: Input uses {context_usage:.1f}% of context limit"
    elif context_usage > 50:
        warning = f"Note: Input uses {context_usage:.1f}% of context limit"

    # Estimate cost
    cost = estimate_cost(input_tokens, estimated_output, model)

    return TokenEstimate(
        input_tokens=input_tokens,
        estimated_output_tokens=estimated_output,
        total_tokens=total_tokens,
        estimated_cost_usd=cost.total_cost_usd,
        context_limit=context_limit,
        context_usage_percent=context_usage,
        context_warning=warning,
    )


def get_context_limit(model: str) -> int:
    """Get context limit for a model."""
    base = _get_model_base(model)
    return CONTEXT_LIMITS.get(base, DEFAULT_CONTEXT_LIMIT)


# =============================================================================
# Output Token Limit Functions
# =============================================================================
# Import output limit constants from app.constants for centralized management.

# Late import to avoid circular dependency at module level
_output_limits_cache: dict[str, int] | None = None
_use_case_defaults_cache: dict[str, int] | None = None


def _get_output_limits() -> dict[str, int]:
    """Get OUTPUT_LIMITS dict, lazy-loaded to avoid circular imports."""
    global _output_limits_cache
    if _output_limits_cache is None:
        from app.constants import OUTPUT_LIMITS

        _output_limits_cache = OUTPUT_LIMITS
    return _output_limits_cache


def _get_use_case_defaults() -> dict[str, int]:
    """Get use-case defaults dict, lazy-loaded to avoid circular imports."""
    global _use_case_defaults_cache
    if _use_case_defaults_cache is None:
        from app.constants import (
            DEFAULT_OUTPUT_LIMIT,
            OUTPUT_LIMIT_AGENTIC,
            OUTPUT_LIMIT_ANALYSIS,
            OUTPUT_LIMIT_CHAT,
            OUTPUT_LIMIT_CODE,
        )

        _use_case_defaults_cache = {
            "chat": OUTPUT_LIMIT_CHAT,
            "code": OUTPUT_LIMIT_CODE,
            "analysis": OUTPUT_LIMIT_ANALYSIS,
            "agentic": OUTPUT_LIMIT_AGENTIC,
            "general": DEFAULT_OUTPUT_LIMIT,
        }
    return _use_case_defaults_cache


def get_output_limit(model: str) -> int:
    """
    Get maximum output tokens for a model.

    Args:
        model: Model identifier (e.g., "claude-sonnet-4-5", "gemini-3-flash-preview")

    Returns:
        Maximum output tokens the model can generate
    """
    from app.constants import DEFAULT_OUTPUT_LIMIT

    base = _get_model_base(model)
    output_limits = _get_output_limits()
    return output_limits.get(base, DEFAULT_OUTPUT_LIMIT)


def get_recommended_max_tokens(
    model: str | None = None,
    use_case: str = "general",
) -> int:
    """
    Get recommended max_tokens default for a model and use case.

    The returned value is the minimum of:
    - The model's maximum output capability
    - The use-case specific default

    Args:
        model: Model identifier. If None, returns use-case default.
        use_case: One of "chat", "code", "analysis", "agentic", "general"

    Returns:
        Recommended max_tokens value

    Examples:
        >>> get_recommended_max_tokens("claude-sonnet-4-5", "chat")
        4096
        >>> get_recommended_max_tokens("claude-sonnet-4-5", "agentic")
        64000
        >>> get_recommended_max_tokens(None, "code")
        16384
    """
    from app.constants import DEFAULT_OUTPUT_LIMIT

    use_case_defaults = _get_use_case_defaults()
    use_case_default = use_case_defaults.get(use_case, DEFAULT_OUTPUT_LIMIT)

    if model is None:
        return use_case_default

    model_max = get_output_limit(model)
    return min(use_case_default, model_max)


# =============================================================================
# Output Usage Tracking
# =============================================================================


@dataclass
class OutputUsage:
    """Output token usage and truncation information."""

    output_tokens: int  # Actual tokens generated
    max_tokens_requested: int  # What user asked for (or default)
    model_limit: int  # Model's max output capability
    was_truncated: bool  # True if finish_reason="max_tokens"
    warning: str | None = None  # Validation or truncation warning


@dataclass
class MaxTokensValidation:
    """Result of validating max_tokens against model limits."""

    is_valid: bool  # False if requested exceeds model limit
    effective_max_tokens: int  # Capped to model limit if exceeded
    model_limit: int  # Model's max output capability
    warning: str | None = None  # Warning message if capped


def validate_max_tokens(model: str, requested_max_tokens: int) -> MaxTokensValidation:
    """
    Validate requested max_tokens against model's output limit.

    If requested exceeds model limit, caps to model limit and returns warning.
    This is a soft validation - we cap rather than reject.

    Args:
        model: Model identifier
        requested_max_tokens: User-requested max_tokens

    Returns:
        Validation result with effective max_tokens and any warning
    """
    model_limit = get_output_limit(model)

    if requested_max_tokens > model_limit:
        return MaxTokensValidation(
            is_valid=False,
            effective_max_tokens=model_limit,
            model_limit=model_limit,
            warning=f"Requested max_tokens ({requested_max_tokens}) exceeds model limit ({model_limit}). Capped to {model_limit}.",
        )

    return MaxTokensValidation(
        is_valid=True,
        effective_max_tokens=requested_max_tokens,
        model_limit=model_limit,
        warning=None,
    )


def build_output_usage(
    output_tokens: int,
    max_tokens_requested: int,
    model: str,
    finish_reason: str | None,
    validation_warning: str | None = None,
) -> OutputUsage:
    """
    Build OutputUsage from completion result.

    Args:
        output_tokens: Actual tokens generated
        max_tokens_requested: User-requested max_tokens (possibly capped)
        model: Model identifier
        finish_reason: Why generation stopped (from API response)
        validation_warning: Warning from max_tokens validation (if any)

    Returns:
        OutputUsage with truncation detection
    """
    model_limit = get_output_limit(model)
    # Check for truncation - handle different provider formats:
    # Claude: "max_tokens", Gemini: "FinishReason.MAX_TOKENS" or "MAX_TOKENS"
    finish_lower = (finish_reason or "").lower()
    was_truncated = "max_tokens" in finish_lower

    warning = validation_warning
    if was_truncated and not warning:
        warning = f"Response truncated at {output_tokens} tokens (max_tokens limit reached)."

    return OutputUsage(
        output_tokens=output_tokens,
        max_tokens_requested=max_tokens_requested,
        model_limit=model_limit,
        was_truncated=was_truncated,
        warning=warning,
    )
