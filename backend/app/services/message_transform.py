"""Cross-provider message transforms for multi-model sessions."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any

from app.adapters.types import Message

_ANTHROPIC_MAX_ID_LEN = 64
_ANTHROPIC_ALLOWED = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
)


def transform_messages(
    messages: list[Message],
    source_provider: str | None,
    target_provider: str,
) -> list[Message]:
    """Transform messages for cross-provider compatibility."""
    result = [deepcopy(msg) for msg in messages]
    result = _convert_thinking_blocks(result, source_provider, target_provider)
    result = _normalize_tool_call_ids(result, target_provider)
    result = _repair_orphaned_tool_calls(result)
    return _filter_error_messages(result)


def _iter_blocks(messages: list[Message]) -> list[dict[str, Any]]:
    return [b for msg in messages if isinstance(msg.content, list)
            for b in msg.content if isinstance(b, dict)]


def _same_family(a: str | None, b: str) -> bool:
    if a is None:
        return False
    anthropic = {"claude", "anthropic"}
    return (a in anthropic and b in anthropic) or a == b


def _normalize_tool_call_ids(messages: list[Message], target_provider: str) -> list[Message]:
    """Normalize tool call IDs for Anthropic constraints (max 64 chars, safe chars)."""
    if target_provider not in ("claude", "anthropic"):
        return messages
    blocks = _iter_blocks(messages)
    if not {b.get("type") for b in blocks} & {"tool_use", "tool_result"}:
        return messages
    id_mapping: dict[str, str] = {}
    for block in blocks:
        btype = block.get("type")
        if btype == "tool_use":
            oid = block.get("id", "")
            if oid and not (len(oid) <= _ANTHROPIC_MAX_ID_LEN and all(c in _ANTHROPIC_ALLOWED for c in oid)):
                new_id = f"tc_{hashlib.sha256(oid.encode()).hexdigest()[:29]}"
                id_mapping[oid] = new_id
                block["id"] = new_id
        elif btype == "tool_result":
            ref = block.get("tool_use_id", "")
            if ref in id_mapping:
                block["tool_use_id"] = id_mapping[ref]
    return messages


def _repair_orphaned_tool_calls(messages: list[Message]) -> list[Message]:
    """Insert synthetic error results for tool_use blocks without a matching tool_result."""
    tool_use_ids: dict[str, int] = {}
    tool_result_ids: set[str] = set()
    for i, msg in enumerate(messages):
        if not isinstance(msg.content, list):
            continue
        for block in msg.content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "tool_use" and (tid := block.get("id", "")):
                tool_use_ids[tid] = i
            elif btype == "tool_result" and (tid := block.get("tool_use_id", "")):
                tool_result_ids.add(tid)
    orphaned = {tid: idx for tid, idx in tool_use_ids.items() if tid not in tool_result_ids}
    if not orphaned:
        return messages
    by_msg_idx: dict[int, list[str]] = {}
    for tid, idx in orphaned.items():
        by_msg_idx.setdefault(idx, []).append(tid)
    result: list[Message] = []
    for i, msg in enumerate(messages):
        result.append(msg)
        if i in by_msg_idx:
            result.append(Message(role="user", content=[
                {"type": "tool_result", "tool_use_id": tid,
                 "content": "No result provided — tool execution was interrupted."}
                for tid in by_msg_idx[i]
            ]))
    return result


def _is_error_block(block: dict[str, Any]) -> bool:
    btype = block.get("type", "")
    if btype == "error":
        return True
    if btype == "text":
        text = (block.get("text", "") or "").strip()
        return not text or text.startswith("Error:")
    return False


def _filter_error_messages(messages: list[Message]) -> list[Message]:
    """Remove assistant messages that contain only error content."""
    result: list[Message] = []
    for msg in messages:
        if msg.role != "assistant":
            result.append(msg)
            continue
        if isinstance(msg.content, str):
            text = msg.content.strip()
            if text and not text.startswith("Error:"):
                result.append(msg)
            continue
        if not isinstance(msg.content, list) or any(
            not isinstance(b, dict) or not _is_error_block(b) for b in msg.content
        ):
            result.append(msg)
    return result


def _convert_thinking_blocks(
    messages: list[Message], source_provider: str | None, target_provider: str
) -> list[Message]:
    """Convert thinking blocks to plain text when switching provider families."""
    if _same_family(source_provider, target_provider):
        return messages
    if not any(b.get("type") == "thinking" for b in _iter_blocks(messages)):
        return messages
    for msg in messages:
        if not isinstance(msg.content, list):
            continue
        new_blocks: list[Any] = []
        for b in msg.content:
            if isinstance(b, dict) and b.get("type") == "thinking":
                raw = b.get("thinking", "") or b.get("text", "")
                text = f"[Previous reasoning]: {raw}" if raw else "[Reasoning omitted]"
                new_blocks.append({"type": "text", "text": text})
            else:
                new_blocks.append(b)
        msg.content = new_blocks if new_blocks else ""
    return messages
