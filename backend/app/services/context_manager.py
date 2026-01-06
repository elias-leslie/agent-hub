"""
Context window management with automatic summarization.

Handles context overflow by summarizing older messages while preserving
recent context and key information.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.adapters.base import Message
from app.services.token_counter import count_message_tokens, get_context_limit

logger = logging.getLogger(__name__)

# Configuration
DEFAULT_PRESERVE_RECENT = 5  # Preserve last N turns (user+assistant pairs)
DEFAULT_TARGET_RATIO = 0.5  # Target 50% of context limit after summarization
SUMMARIZATION_MODEL = "claude-haiku-4-5-20250514"
MAX_SUMMARY_TOKENS = 2000  # Max tokens for summary output


class CompressionStrategy(str, Enum):
    """Strategy for context compression."""

    TRUNCATE = "truncate"  # Simply drop older messages
    SUMMARIZE = "summarize"  # Summarize older messages with LLM
    HYBRID = "hybrid"  # Summarize if possible, truncate as fallback


@dataclass
class CompressionResult:
    """Result of context compression."""

    messages: list[Message]
    original_tokens: int
    compressed_tokens: int
    strategy_used: CompressionStrategy
    summary: str | None = None
    messages_summarized: int = 0
    compression_ratio: float = 0.0


@dataclass
class ContextConfig:
    """Configuration for context management."""

    strategy: CompressionStrategy = CompressionStrategy.HYBRID
    preserve_recent: int = DEFAULT_PRESERVE_RECENT
    target_ratio: float = DEFAULT_TARGET_RATIO
    summarization_enabled: bool = True


def _split_messages(
    messages: list[Message],
    preserve_recent: int,
) -> tuple[Message | None, list[Message], list[Message]]:
    """
    Split messages into system prompt, summarizable messages, and recent messages.

    Args:
        messages: Full message list
        preserve_recent: Number of recent turn pairs to preserve

    Returns:
        Tuple of (system_message, old_messages, recent_messages)
    """
    system_msg: Message | None = None
    conversation: list[Message] = []

    for msg in messages:
        if msg.role == "system":
            system_msg = msg
        else:
            conversation.append(msg)

    # Calculate how many messages to preserve (turns = user + assistant pairs)
    # Preserve at least preserve_recent * 2 messages (user + assistant)
    preserve_count = preserve_recent * 2
    if len(conversation) <= preserve_count:
        return system_msg, [], conversation

    old_messages = conversation[:-preserve_count]
    recent_messages = conversation[-preserve_count:]

    return system_msg, old_messages, recent_messages


def _build_summarization_prompt(messages: list[Message]) -> str:
    """Build prompt for summarizing messages."""
    conversation_text = "\n".join(
        f"{msg.role.upper()}: {msg.content}" for msg in messages
    )

    return f"""Summarize this conversation concisely, preserving:
1. Key decisions and their reasoning
2. Important facts and constraints mentioned
3. Action items or commitments made
4. Technical details that affect future discussion

Be concise but complete. Use bullet points. Do not include any preamble.

CONVERSATION:
{conversation_text}

SUMMARY:"""


async def summarize_messages(
    messages: list[Message],
    adapter: Any,  # ClaudeAdapter instance
) -> str:
    """
    Summarize a list of messages using Claude Haiku.

    Args:
        messages: Messages to summarize
        adapter: Claude adapter for making API calls

    Returns:
        Summary text
    """
    if not messages:
        return ""

    prompt = _build_summarization_prompt(messages)

    try:
        result = await adapter.complete(
            messages=[Message(role="user", content=prompt)],
            model=SUMMARIZATION_MODEL,
            max_tokens=MAX_SUMMARY_TOKENS,
            temperature=0.3,  # Low temp for consistent summaries
        )
        return result.content
    except Exception as e:
        logger.error(f"Summarization failed: {e}")
        raise


def truncate_context(
    messages: list[Message],
    model: str,
    preserve_recent: int = DEFAULT_PRESERVE_RECENT,
) -> CompressionResult:
    """
    Truncate context by dropping older messages.

    Args:
        messages: Full message list
        model: Model to get context limit for
        preserve_recent: Number of recent turns to preserve

    Returns:
        CompressionResult with truncated messages
    """
    original_tokens = count_message_tokens(
        [{"role": m.role, "content": m.content} for m in messages]
    )

    system_msg, old_messages, recent_messages = _split_messages(
        messages, preserve_recent
    )

    # Build truncated message list
    result_messages: list[Message] = []
    if system_msg:
        result_messages.append(system_msg)
    result_messages.extend(recent_messages)

    compressed_tokens = count_message_tokens(
        [{"role": m.role, "content": m.content} for m in result_messages]
    )

    return CompressionResult(
        messages=result_messages,
        original_tokens=original_tokens,
        compressed_tokens=compressed_tokens,
        strategy_used=CompressionStrategy.TRUNCATE,
        messages_summarized=len(old_messages),
        compression_ratio=(
            compressed_tokens / original_tokens if original_tokens > 0 else 1.0
        ),
    )


async def summarize_context(
    messages: list[Message],
    model: str,
    adapter: Any,
    preserve_recent: int = DEFAULT_PRESERVE_RECENT,
) -> CompressionResult:
    """
    Compress context by summarizing older messages.

    Args:
        messages: Full message list
        model: Model to get context limit for
        adapter: Claude adapter for summarization
        preserve_recent: Number of recent turns to preserve

    Returns:
        CompressionResult with summarized context
    """
    original_tokens = count_message_tokens(
        [{"role": m.role, "content": m.content} for m in messages]
    )

    system_msg, old_messages, recent_messages = _split_messages(
        messages, preserve_recent
    )

    # If nothing to summarize, return as-is
    if not old_messages:
        return CompressionResult(
            messages=messages,
            original_tokens=original_tokens,
            compressed_tokens=original_tokens,
            strategy_used=CompressionStrategy.SUMMARIZE,
            compression_ratio=1.0,
        )

    # Generate summary of old messages
    summary = await summarize_messages(old_messages, adapter)

    # Build new message list with summary
    result_messages: list[Message] = []
    if system_msg:
        result_messages.append(system_msg)

    # Add summary as a system-like context message
    summary_msg = Message(
        role="user",
        content=f"[CONVERSATION SUMMARY]\n{summary}\n[END SUMMARY]\n\nContinuing from the above context:",
    )
    result_messages.append(summary_msg)

    # Add placeholder assistant acknowledgment
    result_messages.append(
        Message(role="assistant", content="I understand the context. Let's continue.")
    )

    # Add recent messages
    result_messages.extend(recent_messages)

    compressed_tokens = count_message_tokens(
        [{"role": m.role, "content": m.content} for m in result_messages]
    )

    return CompressionResult(
        messages=result_messages,
        original_tokens=original_tokens,
        compressed_tokens=compressed_tokens,
        strategy_used=CompressionStrategy.SUMMARIZE,
        summary=summary,
        messages_summarized=len(old_messages),
        compression_ratio=(
            compressed_tokens / original_tokens if original_tokens > 0 else 1.0
        ),
    )


async def compress_context(
    messages: list[Message],
    model: str,
    config: ContextConfig | None = None,
    adapter: Any | None = None,
) -> CompressionResult:
    """
    Compress context using configured strategy.

    Args:
        messages: Full message list
        model: Model identifier (for context limit)
        config: Compression configuration
        adapter: Claude adapter (required for summarization)

    Returns:
        CompressionResult with compressed messages
    """
    if config is None:
        config = ContextConfig()

    original_tokens = count_message_tokens(
        [{"role": m.role, "content": m.content} for m in messages]
    )
    context_limit = get_context_limit(model)
    target_tokens = int(context_limit * config.target_ratio)

    # If under target, no compression needed
    if original_tokens <= target_tokens:
        return CompressionResult(
            messages=messages,
            original_tokens=original_tokens,
            compressed_tokens=original_tokens,
            strategy_used=config.strategy,
            compression_ratio=1.0,
        )

    # Apply compression strategy
    if config.strategy == CompressionStrategy.TRUNCATE:
        return truncate_context(messages, model, config.preserve_recent)

    elif config.strategy == CompressionStrategy.SUMMARIZE:
        if adapter is None:
            raise ValueError("Adapter required for summarization strategy")
        return await summarize_context(messages, model, adapter, config.preserve_recent)

    else:  # HYBRID
        # Try summarization first, fall back to truncation
        if adapter is not None and config.summarization_enabled:
            try:
                result = await summarize_context(
                    messages, model, adapter, config.preserve_recent
                )
                # If summarization achieved good compression, use it
                if result.compressed_tokens <= target_tokens:
                    return result
            except Exception as e:
                logger.warning(f"Summarization failed, falling back to truncation: {e}")

        # Fall back to truncation
        return truncate_context(messages, model, config.preserve_recent)


def needs_compression(
    messages: list[Message],
    model: str,
    threshold_percent: float = 75.0,
) -> bool:
    """
    Check if context needs compression.

    Args:
        messages: Message list to check
        model: Model identifier
        threshold_percent: Trigger compression above this % of limit

    Returns:
        True if compression is recommended
    """
    tokens = count_message_tokens(
        [{"role": m.role, "content": m.content} for m in messages]
    )
    limit = get_context_limit(model)
    percent_used = (tokens / limit * 100) if limit > 0 else 0

    return percent_used >= threshold_percent


def estimate_compression(
    messages: list[Message],
    model: str,
    preserve_recent: int = DEFAULT_PRESERVE_RECENT,
) -> dict[str, Any]:
    """
    Estimate compression results without actually compressing.

    Args:
        messages: Message list
        model: Model identifier
        preserve_recent: Messages to preserve

    Returns:
        Dictionary with compression estimates
    """
    original_tokens = count_message_tokens(
        [{"role": m.role, "content": m.content} for m in messages]
    )

    system_msg, old_messages, recent_messages = _split_messages(
        messages, preserve_recent
    )

    # Estimate truncation result
    truncated_msgs: list[Message] = []
    if system_msg:
        truncated_msgs.append(system_msg)
    truncated_msgs.extend(recent_messages)
    truncated_tokens = count_message_tokens(
        [{"role": m.role, "content": m.content} for m in truncated_msgs]
    )

    # Estimate summarization (assume ~10% of original for summary)
    old_tokens = count_message_tokens(
        [{"role": m.role, "content": m.content} for m in old_messages]
    )
    estimated_summary_tokens = max(200, int(old_tokens * 0.1))
    summarized_tokens = truncated_tokens + estimated_summary_tokens + 50  # overhead

    context_limit = get_context_limit(model)

    return {
        "original_tokens": original_tokens,
        "context_limit": context_limit,
        "percent_used": round(original_tokens / context_limit * 100, 1),
        "messages_to_summarize": len(old_messages),
        "messages_to_preserve": len(recent_messages) + (1 if system_msg else 0),
        "truncation": {
            "estimated_tokens": truncated_tokens,
            "compression_ratio": round(truncated_tokens / original_tokens, 2),
        },
        "summarization": {
            "estimated_tokens": summarized_tokens,
            "compression_ratio": round(summarized_tokens / original_tokens, 2),
        },
    }
