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

import logging
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal

from app.adapters.base import Message, ToolCallIdNormalizer

logger = logging.getLogger(__name__)

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

    Central transformation function following pi-mono pattern:
    - Handles thinking blocks (preserve for same provider, convert for different)
    - Normalizes tool call IDs via ToolCallIdNormalizer
    - Resolves orphaned tool calls (tool_use without tool_result)
    - Filters error messages

    Args:
        messages: List of messages to transform
        source_provider: Provider the messages came from
        target_provider: Provider the messages are going to
        normalize_tool_ids: Whether to normalize tool call IDs

    Returns:
        TransformResult with transformed messages and transformation stats
    """
    same_provider = _is_same_provider(source_provider, target_provider)
    transformed: list[Message] = []

    stats = TransformResult(
        messages=[],
        thinking_converted=0,
        tool_ids_normalized=0,
        orphaned_resolved=0,
        errors_filtered=0,
    )

    pending_tool_calls: dict[str, dict[str, Any]] = {}
    id_mapping: dict[str, str] = {}

    for msg in messages:
        new_msg = _transform_message(
            msg,
            same_provider,
            target_provider,
            normalize_tool_ids,
            pending_tool_calls,
            id_mapping,
            stats,
        )
        if new_msg is not None:
            transformed.append(new_msg)

    orphan_count = _resolve_orphaned_tool_calls(transformed, pending_tool_calls)
    stats.orphaned_resolved = orphan_count

    stats.messages = transformed
    return stats


def _is_same_provider(source: Provider, target: Provider) -> bool:
    """Check if source and target are the same provider family."""
    anthropic_family = {"claude", "anthropic"}
    if source in anthropic_family and target in anthropic_family:
        return True
    return source == target


def _transform_message(
    msg: Message,
    same_provider: bool,
    target_provider: Provider,
    normalize_tool_ids: bool,
    pending_tool_calls: dict[str, dict[str, Any]],
    id_mapping: dict[str, str],
    stats: TransformResult,
) -> Message | None:
    """Transform a single message.

    Returns None if the message should be filtered out.
    """
    if isinstance(msg.content, str):
        return msg

    transformed_blocks: list[dict[str, Any]] = []

    for block in msg.content:
        if not isinstance(block, dict):
            transformed_blocks.append(block)
            continue

        block_type = block.get("type", "")

        if block_type == "thinking":
            new_block = _transform_thinking_block(block, same_provider, stats)
            if new_block:
                transformed_blocks.append(new_block)

        elif block_type == "tool_use":
            new_block = _transform_tool_use_block(
                block, target_provider, normalize_tool_ids, pending_tool_calls, id_mapping, stats
            )
            transformed_blocks.append(new_block)

        elif block_type == "tool_result":
            new_block = _transform_tool_result_block(block, pending_tool_calls, id_mapping, stats)
            transformed_blocks.append(new_block)

        elif block_type == "error":
            stats.errors_filtered += 1
            continue

        else:
            transformed_blocks.append(block)

    if not transformed_blocks:
        return None

    if len(transformed_blocks) == 1 and transformed_blocks[0].get("type") == "text":
        return Message(role=msg.role, content=transformed_blocks[0].get("text", ""))

    return Message(role=msg.role, content=transformed_blocks)


def _transform_thinking_block(
    block: dict[str, Any],
    same_provider: bool,
    stats: TransformResult,
) -> dict[str, Any] | None:
    """Transform thinking block based on provider compatibility.

    Same provider: Preserve thinking block signature
    Different provider: Convert to text block (prefix with [Thinking])
    """
    if same_provider:
        return block

    thinking_text = block.get("thinking", "") or block.get("text", "")
    if not thinking_text:
        return None

    stats.thinking_converted += 1
    return {
        "type": "text",
        "text": f"[Thinking]\n{thinking_text}\n[/Thinking]",
    }


def _transform_tool_use_block(
    block: dict[str, Any],
    target_provider: Provider,
    normalize_tool_ids: bool,
    pending_tool_calls: dict[str, dict[str, Any]],
    id_mapping: dict[str, str],
    stats: TransformResult,
) -> dict[str, Any]:
    """Transform tool_use block with ID normalization."""
    block = deepcopy(block)
    original_id = block.get("id", "")

    if normalize_tool_ids and original_id:
        normalized_id, kept_original = ToolCallIdNormalizer.normalize(
            original_id, _provider_to_normalizer_target(target_provider)
        )
        if kept_original:
            block["id"] = normalized_id
            id_mapping[original_id] = normalized_id
            stats.tool_ids_normalized += 1

    current_id = block.get("id", original_id)
    pending_tool_calls[current_id] = block

    return block


def _transform_tool_result_block(
    block: dict[str, Any],
    pending_tool_calls: dict[str, dict[str, Any]],
    id_mapping: dict[str, str],
    stats: TransformResult,
) -> dict[str, Any]:
    """Transform tool_result block with ID mapping."""
    block = deepcopy(block)
    tool_use_id = block.get("tool_use_id", "")

    if tool_use_id in id_mapping:
        block["tool_use_id"] = id_mapping[tool_use_id]
        stats.tool_ids_normalized += 1

    resolved_id = block.get("tool_use_id", tool_use_id)
    pending_tool_calls.pop(resolved_id, None)
    pending_tool_calls.pop(tool_use_id, None)

    return block


def _resolve_orphaned_tool_calls(
    messages: list[Message],
    pending_tool_calls: dict[str, dict[str, Any]],
) -> int:
    """Inject synthetic tool_result for orphaned tool_use blocks.

    Orphaned tool calls (tool_use without corresponding tool_result) can cause
    API errors. This function injects synthetic results to resolve them.

    Returns:
        Number of orphaned tool calls resolved
    """
    if not pending_tool_calls:
        return 0

    orphaned_count = len(pending_tool_calls)
    logger.warning(f"Resolving {orphaned_count} orphaned tool calls")

    synthetic_results: list[dict[str, Any]] = []
    for tool_id, tool_call in pending_tool_calls.items():
        tool_name = tool_call.get("name", "unknown")
        synthetic_results.append(
            {
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": f"[Session interrupted - {tool_name} result not available]",
                "is_error": True,
            }
        )

    if synthetic_results and messages:
        last_assistant_idx = None
        for i, msg in enumerate(messages):
            if msg.role == "assistant":
                last_assistant_idx = i

        if last_assistant_idx is not None:
            insert_idx = last_assistant_idx + 1
            if insert_idx < len(messages):
                existing = messages[insert_idx]
                if existing.role == "user":
                    if isinstance(existing.content, list):
                        existing.content = [*synthetic_results, *existing.content]
                    else:
                        messages[insert_idx] = Message(
                            role="user",
                            content=[
                                *synthetic_results,
                                {"type": "text", "text": str(existing.content)},
                            ],
                        )
                else:
                    messages.insert(insert_idx, Message(role="user", content=synthetic_results))
            else:
                messages.append(Message(role="user", content=synthetic_results))

    pending_tool_calls.clear()
    return orphaned_count


def _provider_to_normalizer_target(provider: Provider) -> str:
    """Map provider to normalizer target string."""
    if provider in ("claude", "anthropic"):
        return "anthropic"
    return provider


def anthropic_normalize_id(tool_id: str) -> tuple[str, str | None]:
    """Normalize tool ID for Anthropic/Claude constraints.

    - Max 64 characters
    - Alphanumeric, underscore, hyphen only
    """
    return ToolCallIdNormalizer.normalize(tool_id, "anthropic")


def gemini_normalize_id(tool_id: str) -> tuple[str, str | None]:
    """Normalize tool ID for Gemini constraints.

    Gemini uses function names as IDs, so no normalization needed.
    """
    return ToolCallIdNormalizer.normalize(tool_id, "gemini")


def openai_normalize_id(tool_id: str) -> tuple[str, str | None]:
    """Normalize tool ID for OpenAI constraints.

    OpenAI IDs can be long with pipes, but some endpoints have limits.
    For now, apply same constraints as Anthropic.
    """
    return ToolCallIdNormalizer.normalize(tool_id, "anthropic")


def get_normalizer_for_provider(provider: Provider) -> Callable[[str], tuple[str, str | None]]:
    """Get the appropriate ID normalizer for a provider."""
    normalizers: dict[str, Callable[[str], tuple[str, str | None]]] = {
        "claude": anthropic_normalize_id,
        "anthropic": anthropic_normalize_id,
        "gemini": gemini_normalize_id,
        "openai": openai_normalize_id,
    }
    return normalizers.get(provider, anthropic_normalize_id)
