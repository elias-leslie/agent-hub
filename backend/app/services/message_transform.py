"""Cross-provider message transforms for multi-model sessions."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any

from app.adapters.types import Message

# Anthropic ID constraints: max 64 chars, alphanumeric + underscore/hyphen
_ANTHROPIC_MAX_ID_LEN = 64
_ANTHROPIC_ALLOWED = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
)


def transform_messages(
    messages: list[Message],
    source_provider: str | None,
    target_provider: str,
) -> list[Message]:
    """Transform messages for cross-provider compatibility.

    Applies: thinking->text conversion, tool call ID normalization,
    orphaned tool call repair, error message filtering.
    """
    result = [deepcopy(msg) for msg in messages]
    result = _convert_thinking_blocks(result, source_provider, target_provider)
    result = _normalize_tool_call_ids(result, target_provider)
    result = _repair_orphaned_tool_calls(result)
    result = _filter_error_messages(result)
    return result


# ---------------------------------------------------------------------------
# 1. Tool call ID normalization
# ---------------------------------------------------------------------------


def _is_valid_anthropic_id(id_str: str) -> bool:
    return len(id_str) <= _ANTHROPIC_MAX_ID_LEN and all(
        c in _ANTHROPIC_ALLOWED for c in id_str
    )


def _make_normalized_id(original: str) -> str:
    return f"tc_{hashlib.sha256(original.encode()).hexdigest()[:29]}"


def _normalize_tool_call_ids(
    messages: list[Message], target_provider: str
) -> list[Message]:
    """Normalize tool call IDs for target provider constraints.

    When targeting Anthropic/Claude, truncate and hash IDs that exceed 64 chars
    or contain disallowed characters. Maintains a mapping so tool_result blocks
    still reference the correct tool_use.
    """
    if target_provider not in ("claude", "anthropic"):
        return messages

    # Quick check: do any messages contain tool-related content?
    has_tool_content = False
    for msg in messages:
        if isinstance(msg.content, list):
            for block in msg.content:
                if isinstance(block, dict) and block.get("type") in (
                    "tool_use",
                    "tool_result",
                ):
                    has_tool_content = True
                    break
            if has_tool_content:
                break
    if not has_tool_content:
        return messages

    id_mapping: dict[str, str] = {}

    for msg in messages:
        if not isinstance(msg.content, list):
            continue
        for block in msg.content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")

            if btype == "tool_use":
                original_id = block.get("id", "")
                if original_id and not _is_valid_anthropic_id(original_id):
                    new_id = _make_normalized_id(original_id)
                    id_mapping[original_id] = new_id
                    block["id"] = new_id

            elif btype == "tool_result":
                ref_id = block.get("tool_use_id", "")
                if ref_id in id_mapping:
                    block["tool_use_id"] = id_mapping[ref_id]

    return messages


# ---------------------------------------------------------------------------
# 2. Orphaned tool call repair
# ---------------------------------------------------------------------------


def _repair_orphaned_tool_calls(messages: list[Message]) -> list[Message]:
    """Insert synthetic error results for tool_use blocks without a matching tool_result.

    When an assistant message has tool_calls but the conversation was interrupted
    before results were provided, inject a user message with error tool_results
    to prevent API errors on replay.
    """
    # Collect all tool_use IDs and tool_result IDs
    tool_use_ids: dict[str, int] = {}  # id -> index of the message containing it
    tool_result_ids: set[str] = set()

    for i, msg in enumerate(messages):
        if not isinstance(msg.content, list):
            continue
        for block in msg.content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "tool_use":
                tid = block.get("id", "")
                if tid:
                    tool_use_ids[tid] = i
            elif btype == "tool_result":
                tid = block.get("tool_use_id", "")
                if tid:
                    tool_result_ids.add(tid)

    orphaned = {
        tid: idx for tid, idx in tool_use_ids.items() if tid not in tool_result_ids
    }
    if not orphaned:
        return messages

    # Group orphaned IDs by the message index they appear in (to insert after)
    by_msg_idx: dict[int, list[str]] = {}
    for tid, idx in orphaned.items():
        by_msg_idx.setdefault(idx, []).append(tid)

    # Build new message list, inserting synthetic results after the relevant assistant message
    result: list[Message] = []
    for i, msg in enumerate(messages):
        result.append(msg)
        if i in by_msg_idx:
            synthetic_blocks: list[dict[str, Any]] = []
            for tid in by_msg_idx[i]:
                synthetic_blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tid,
                        "content": "No result provided — tool execution was interrupted.",
                    }
                )
            result.append(Message(role="user", content=synthetic_blocks))

    return result


# ---------------------------------------------------------------------------
# 3. Error message filtering
# ---------------------------------------------------------------------------


def _filter_error_messages(messages: list[Message]) -> list[Message]:
    """Remove assistant messages that contain only error content."""
    result: list[Message] = []
    for msg in messages:
        if msg.role != "assistant":
            result.append(msg)
            continue

        if isinstance(msg.content, str):
            text = msg.content.strip()
            if not text or text.startswith("Error:"):
                continue
            result.append(msg)
            continue

        # list content: check if every block is an error or empty
        if isinstance(msg.content, list):
            has_non_error = False
            for block in msg.content:
                if not isinstance(block, dict):
                    has_non_error = True
                    break
                btype = block.get("type", "")
                if btype == "error":
                    continue
                if btype == "text":
                    text = (block.get("text", "") or "").strip()
                    if not text or text.startswith("Error:"):
                        continue
                has_non_error = True
                break
            if not has_non_error:
                continue

        result.append(msg)

    return result


# ---------------------------------------------------------------------------
# 4. Thinking block conversion
# ---------------------------------------------------------------------------


def _convert_thinking_blocks(
    messages: list[Message],
    source_provider: str | None,
    target_provider: str,
) -> list[Message]:
    """Convert thinking blocks to plain text when switching providers.

    If source and target are the same provider family, thinking blocks are
    left unchanged. Otherwise, thinking blocks become text blocks prefixed
    with '[Previous reasoning]:'.
    """
    if _same_family(source_provider, target_provider):
        return messages

    # Check if any message has thinking blocks
    has_thinking = False
    for msg in messages:
        if isinstance(msg.content, list):
            for block in msg.content:
                if isinstance(block, dict) and block.get("type") == "thinking":
                    has_thinking = True
                    break
            if has_thinking:
                break
    if not has_thinking:
        return messages

    for msg in messages:
        if not isinstance(msg.content, list):
            continue
        new_blocks: list[dict[str, Any]] = []
        for block in msg.content:
            if isinstance(block, dict) and block.get("type") == "thinking":
                thinking_text = block.get("thinking", "") or block.get("text", "")
                if thinking_text:
                    converted_text = f"[Previous reasoning]: {thinking_text}"
                else:
                    # Empty thinking block: use placeholder so the block is not
                    # silently dropped by the error filter (which strips empty text).
                    converted_text = "[Reasoning omitted]"
                new_blocks.append({"type": "text", "text": converted_text})
            else:
                new_blocks.append(block)
        msg.content = new_blocks if new_blocks else ""

    return messages


def _same_family(a: str | None, b: str) -> bool:
    """Check whether two provider names refer to the same family."""
    if a is None:
        return False
    anthropic = {"claude", "anthropic"}
    if a in anthropic and b in anthropic:
        return True
    return a == b
