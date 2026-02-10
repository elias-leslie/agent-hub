"""Cross-provider message transformation for reliable failover.

Implements the pi-mono pattern: central transform_messages function with
per-adapter normalizers for provider-specific constraints.

Key transformations:
- Thinking blocks: Preserve signature for same provider, convert to text for different
- Tool call IDs: Normalize using ToolCallIdNormalizer
- Orphaned tool calls: Inject synthetic results for tool_use without tool_result
- Error messages: Filter aborted/error stops
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from app.adapters.base import Message, ToolCallIdNormalizer
from app.services.message_blocks import (
    resolve_orphaned_tool_calls,
    transform_thinking_block,
    transform_tool_result_block,
    transform_tool_use_block,
)

Provider = Literal["claude", "anthropic", "gemini", "openai"]


@dataclass
class TransformResult:
    """Result of message transformation."""

    messages: list[Message]
    thinking_converted: int  # Number of thinking blocks converted to text
    tool_ids_normalized: int  # Number of tool IDs normalized
    orphaned_resolved: int  # Number of orphaned tool calls resolved
    errors_filtered: int  # Number of error messages filtered


def transform_messages(
    messages: list[Message],
    source_provider: Provider,
    target_provider: Provider,
    normalize_tool_ids: bool = True,
) -> TransformResult:
    """Transform messages for cross-provider compatibility.

    Handles: thinking blocks, tool ID normalization, orphaned tool calls, error filtering.
    """
    same_provider = _is_same_provider(source_provider, target_provider)
    normalizer_target = _provider_to_normalizer_target(target_provider)
    stats = TransformResult([], 0, 0, 0, 0)
    pending_tool_calls: dict[str, dict[str, Any]] = {}
    id_mapping: dict[str, str] = {}
    transformed: list[Message] = []

    for msg in messages:
        new_msg = _transform_message(
            msg, same_provider, normalizer_target, normalize_tool_ids,
            pending_tool_calls, id_mapping, stats
        )
        if new_msg is not None:
            transformed.append(new_msg)

    stats.orphaned_resolved = resolve_orphaned_tool_calls(transformed, pending_tool_calls)
    stats.messages = transformed
    return stats


def _is_same_provider(source: Provider, target: Provider) -> bool:
    """Check if source and target are the same provider family."""
    anthropic_family = {"claude", "anthropic"}
    if source in anthropic_family and target in anthropic_family:
        return True
    return source == target


def _provider_to_normalizer_target(provider: Provider) -> str:
    """Map provider to normalizer target string."""
    if provider in ("claude", "anthropic"):
        return "anthropic"
    return provider


def _transform_message(
    msg: Message, same_provider: bool, normalizer_target: str, normalize_tool_ids: bool,
    pending_tool_calls: dict[str, dict[str, Any]], id_mapping: dict[str, str], stats: TransformResult,
) -> Message | None:
    """Transform a single message. Returns None if filtered out."""
    if isinstance(msg.content, str):
        return msg

    transformed_blocks: list[dict[str, Any]] = []
    for block in msg.content:
        if not isinstance(block, dict):
            transformed_blocks.append(block)
            continue
        transformed_block = _transform_block(
            block, same_provider, normalizer_target, normalize_tool_ids,
            pending_tool_calls, id_mapping, stats
        )
        if transformed_block is not None:
            transformed_blocks.append(transformed_block)

    if not transformed_blocks:
        return None
    if len(transformed_blocks) == 1 and transformed_blocks[0].get("type") == "text":
        return Message(role=msg.role, content=transformed_blocks[0].get("text", ""))
    return Message(role=msg.role, content=transformed_blocks)


def _transform_block(
    block: dict[str, Any], same_provider: bool, normalizer_target: str, normalize_tool_ids: bool,
    pending_tool_calls: dict[str, dict[str, Any]], id_mapping: dict[str, str], stats: TransformResult,
) -> dict[str, Any] | None:
    """Transform a single content block based on its type."""
    block_type = block.get("type", "")

    if block_type == "thinking":
        new_block = transform_thinking_block(block, same_provider)
        if new_block and new_block.get("type") == "text":
            stats.thinking_converted += 1
        return new_block
    if block_type == "tool_use":
        new_block, norm_count = transform_tool_use_block(
            block, normalizer_target, normalize_tool_ids, pending_tool_calls, id_mapping
        )
        stats.tool_ids_normalized += norm_count
        return new_block
    if block_type == "tool_result":
        new_block, norm_count = transform_tool_result_block(block, pending_tool_calls, id_mapping)
        stats.tool_ids_normalized += norm_count
        return new_block
    if block_type == "error":
        stats.errors_filtered += 1
        return None
    return block


# Provider-specific normalizer functions (backward compatibility)
_NORMALIZER_TARGETS: dict[str, str] = {
    "claude": "anthropic",
    "anthropic": "anthropic",
    "gemini": "gemini",
    "openai": "anthropic",
}


def anthropic_normalize_id(tool_id: str) -> tuple[str, str | None]:
    """Normalize tool ID for Anthropic/Claude constraints."""
    return ToolCallIdNormalizer.normalize(tool_id, "anthropic")


def gemini_normalize_id(tool_id: str) -> tuple[str, str | None]:
    """Normalize tool ID for Gemini constraints."""
    return ToolCallIdNormalizer.normalize(tool_id, "gemini")


def openai_normalize_id(tool_id: str) -> tuple[str, str | None]:
    """Normalize tool ID for OpenAI constraints."""
    return ToolCallIdNormalizer.normalize(tool_id, "anthropic")


def get_normalizer_for_provider(provider: Provider) -> Callable[[str], tuple[str, str | None]]:
    """Get the appropriate ID normalizer for a provider."""
    target = _NORMALIZER_TARGETS.get(provider, "anthropic")
    return lambda tool_id: ToolCallIdNormalizer.normalize(tool_id, target)
