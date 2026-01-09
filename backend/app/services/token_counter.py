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
    max_tokens: int = 4096,
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
