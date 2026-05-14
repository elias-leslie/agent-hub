"""
Token counting and cost estimation service.

Uses tiktoken for accurate token counting before API calls.
Pricing and context limits derived from MODEL_CATALOG (single source of truth).
"""

import logging
from dataclasses import dataclass
from typing import Any

import tiktoken

from app.constants import MODEL_CATALOG, MODEL_CATALOG_BY_ID, ModelEntry
from app.constants.models import GEMINI_FLASH

logger = logging.getLogger(__name__)

# Default fallback for unknown models
_DEFAULT_CONTEXT_LIMIT = 100_000


def _resolve_model(model: str) -> ModelEntry | None:
    """Resolve a model ID (exact or prefix) to its catalog entry."""
    # Exact match first
    if model in MODEL_CATALOG_BY_ID:
        return MODEL_CATALOG_BY_ID[model]
    # Prefix match for dated provider telemetry ids.
    model_lower = model.lower()
    for entry in MODEL_CATALOG:
        if model_lower.startswith(entry.id):
            return entry
    # Substring match for provider variants.
    for entry in MODEL_CATALOG:
        if entry.id.startswith(model_lower) or model_lower in entry.id:
            return entry
    return None


def _get_model_entry(model: str) -> ModelEntry:
    """Get catalog entry for a model, falling back to a routable baseline."""
    entry = _resolve_model(model)
    if entry is not None:
        return entry
    return MODEL_CATALOG_BY_ID[GEMINI_FLASH]


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


def _get_encoding() -> tiktoken.Encoding:
    """Get a broadly compatible tiktoken encoding."""
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


def _count_block_tokens(block: Any, encoding: tiktoken.Encoding) -> int:
    """Count tokens for a single content block (dict or string)."""
    if isinstance(block, str):
        return len(encoding.encode(block))
    if not isinstance(block, dict):
        return 0
    block_type = block.get("type", "")
    if block_type == "text":
        return len(encoding.encode(block.get("text", "")))
    if block_type == "image":
        return 1000  # Estimate ~1000 tokens per image (varies by size/resolution)
    return 0


def _count_content_tokens(content: Any, encoding: tiktoken.Encoding) -> int:
    """Count tokens for message content (string or list of blocks)."""
    if not isinstance(content, list):
        return len(encoding.encode(content))
    return sum(_count_block_tokens(block, encoding) for block in content)


def count_message_tokens(messages: list[dict[str, Any]]) -> int:
    """Count tokens in a list of messages including per-message overhead.

    Handles multi-modal content (text + images) for vision API.

    Args:
        messages: List of message dicts with "role" and "content"
                  Content can be a string or list of content blocks.

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
        total += _count_content_tokens(content, encoding)
    # Priming tokens at start
    total += 2
    return total


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    model: str,
    cached_input_tokens: int = 0,
) -> CostBreakdown:
    """Calculate cost for a request.

    Args:
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens
        model: Model identifier
        cached_input_tokens: Number of cached input tokens, when supported

    Returns:
        Cost breakdown in USD
    """
    entry = _get_model_entry(model)
    cost = entry.cost

    # Calculate costs per million tokens
    uncached_input = input_tokens - cached_input_tokens
    input_cost = (uncached_input / 1_000_000) * cost.input_per_m
    cached_rate = cost.cache_read_per_million or 0.0
    cached_cost = (cached_input_tokens / 1_000_000) * cached_rate
    output_cost = (output_tokens / 1_000_000) * cost.output_per_m

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
    """Estimate tokens and cost for a request before sending.

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

    # Get context limit from catalog
    context_limit = get_context_limit(model)
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
    """Get context limit for a model from the catalog."""
    entry = _resolve_model(model)
    if entry is not None:
        return entry.context_window
    return _DEFAULT_CONTEXT_LIMIT


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


def build_output_usage(
    output_tokens: int,
    max_tokens_requested: int | None,
    model: str,
    finish_reason: str | None,
    validation_warning: str | None = None,
) -> OutputUsage:
    """
    Build OutputUsage from completion result.

    Args:
        output_tokens: Actual tokens generated
        max_tokens_requested: User-requested max_tokens (None if not specified)
        model: Model identifier
        finish_reason: Why generation stopped (from API response)
        validation_warning: Warning from max_tokens validation (if any)

    Returns:
        OutputUsage with truncation detection
    """
    # Check for truncation across provider-specific finish_reason formats.
    finish_lower = (finish_reason or "").lower()
    was_truncated = "max_tokens" in finish_lower

    warning = validation_warning
    if was_truncated and not warning:
        warning = f"Response truncated at {output_tokens} tokens (model max_tokens limit reached)."

    return OutputUsage(
        output_tokens=output_tokens,
        max_tokens_requested=max_tokens_requested or 0,
        model_limit=0,  # No longer tracking artificial limits
        was_truncated=was_truncated,
        warning=warning,
    )
