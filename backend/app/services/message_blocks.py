"""Message block transformation utilities.

Handles individual content block transformations:
- Thinking blocks (preserve/convert based on provider)
- Tool use blocks (ID normalization, orphan tracking)
- Tool result blocks (ID mapping)
- Orphaned tool call resolution
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from app.adapters.base import Message, ToolCallIdNormalizer

logger = logging.getLogger(__name__)


def transform_thinking_block(
    block: dict[str, Any],
    same_provider: bool,
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

    return {
        "type": "text",
        "text": f"[Thinking]\n{thinking_text}\n[/Thinking]",
    }


def transform_tool_use_block(
    block: dict[str, Any],
    target_provider: str,
    normalize_tool_ids: bool,
    pending_tool_calls: dict[str, dict[str, Any]],
    id_mapping: dict[str, str],
) -> tuple[dict[str, Any], int]:
    """Transform tool_use block with ID normalization.

    Returns:
        Tuple of (transformed_block, normalization_count)
    """
    block = deepcopy(block)
    original_id = block.get("id", "")
    normalized_count = 0

    if normalize_tool_ids and original_id:
        normalized_id, kept_original = ToolCallIdNormalizer.normalize(
            original_id, target_provider
        )
        if kept_original:
            block["id"] = normalized_id
            id_mapping[original_id] = normalized_id
            normalized_count = 1

    current_id = block.get("id", original_id)
    pending_tool_calls[current_id] = block

    return block, normalized_count


def transform_tool_result_block(
    block: dict[str, Any],
    pending_tool_calls: dict[str, dict[str, Any]],
    id_mapping: dict[str, str],
) -> tuple[dict[str, Any], int]:
    """Transform tool_result block with ID mapping.

    Returns:
        Tuple of (transformed_block, normalization_count)
    """
    block = deepcopy(block)
    tool_use_id = block.get("tool_use_id", "")
    normalized_count = 0

    if tool_use_id in id_mapping:
        block["tool_use_id"] = id_mapping[tool_use_id]
        normalized_count = 1

    resolved_id = block.get("tool_use_id", tool_use_id)
    pending_tool_calls.pop(resolved_id, None)
    pending_tool_calls.pop(tool_use_id, None)

    return block, normalized_count


def resolve_orphaned_tool_calls(
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
