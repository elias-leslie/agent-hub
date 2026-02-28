"""Cross-provider message transforms for multi-model sessions."""

from __future__ import annotations

import hashlib
from copy import deepcopy

from app.adapters.types import Message

_ANTHROPIC_MAX_ID_LEN = 64
_ANTHROPIC_ALLOWED = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")

Block = dict[str, object]


def _str_val(block: Block, key: str) -> str:
    """Return block[key] as str, or '' if missing/None."""
    val = block.get(key)
    return str(val) if val is not None else ""


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


def _iter_blocks(messages: list[Message]) -> list[Block]:
    return [
        b
        for msg in messages
        if isinstance(msg.content, list)
        for b in msg.content
        if isinstance(b, dict)
    ]


def _same_family(a: str | None, b: str) -> bool:
    if a is None:
        return False
    anthropic = {"claude", "anthropic"}
    return (a in anthropic and b in anthropic) or a == b


def _normalize_tool_use_id(block: Block, id_mapping: dict[str, str]) -> None:
    """Normalize a tool_use block's ID and record mapping if changed."""
    oid = _str_val(block, "id")
    if not oid:
        return
    if len(oid) <= _ANTHROPIC_MAX_ID_LEN and all(c in _ANTHROPIC_ALLOWED for c in oid):
        return
    new_id = f"tc_{hashlib.sha256(oid.encode()).hexdigest()[:29]}"
    id_mapping[oid] = new_id
    block["id"] = new_id


def _remap_tool_result_id(block: Block, id_mapping: dict[str, str]) -> None:
    """Update tool_result block's tool_use_id if it was remapped."""
    ref = _str_val(block, "tool_use_id")
    if ref in id_mapping:
        block["tool_use_id"] = id_mapping[ref]


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
            _normalize_tool_use_id(block, id_mapping)
        elif btype == "tool_result":
            _remap_tool_result_id(block, id_mapping)
    return messages


def _register_block_tool_id(
    block: object,
    msg_index: int,
    tool_use_ids: dict[str, int],
    tool_result_ids: set[str],
) -> None:
    """Register tool_use or tool_result IDs from a single block."""
    if not isinstance(block, dict):
        return
    btype = block.get("type")
    if btype == "tool_use":
        tid = _str_val(block, "id")
        if tid:
            tool_use_ids[tid] = msg_index
    elif btype == "tool_result":
        tid = _str_val(block, "tool_use_id")
        if tid:
            tool_result_ids.add(tid)


def _collect_tool_ids(messages: list[Message]) -> tuple[dict[str, int], set[str]]:
    """Return (tool_use_id -> message_index, set of tool_result_ids)."""
    tool_use_ids: dict[str, int] = {}
    tool_result_ids: set[str] = set()
    for i, msg in enumerate(messages):
        if not isinstance(msg.content, list):
            continue
        for block in msg.content:
            _register_block_tool_id(block, i, tool_use_ids, tool_result_ids)
    return tool_use_ids, tool_result_ids


def _repair_orphaned_tool_calls(messages: list[Message]) -> list[Message]:
    """Insert synthetic error results for tool_use blocks without a matching tool_result."""
    tool_use_ids, tool_result_ids = _collect_tool_ids(messages)
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
            result.append(
                Message(
                    role="user",
                    content=[
                        {
                            "type": "tool_result",
                            "tool_use_id": tid,
                            "content": "No result provided — tool execution was interrupted.",
                        }
                        for tid in by_msg_idx[i]
                    ],
                )
            )
    return result


def _is_error_block(block: Block) -> bool:
    btype = block.get("type")
    if btype == "error":
        return True
    if btype == "text":
        raw = block.get("text")
        text = (str(raw) if raw is not None else "").strip()
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


def _convert_thinking_block(b: Block) -> Block:
    """Convert a single thinking block to a plain text block."""
    raw = b.get("thinking") or b.get("text")
    text = f"[Previous reasoning]: {raw}" if raw else "[Reasoning omitted]"
    return {"type": "text", "text": text}


def _rewrite_message_blocks(msg: Message) -> None:
    """Replace thinking blocks in-place with plain text equivalents."""
    if not isinstance(msg.content, list):
        return
    new_blocks: list[Block] = []
    for b in msg.content:
        if isinstance(b, dict) and b.get("type") == "thinking":
            new_blocks.append(_convert_thinking_block(b))
        elif isinstance(b, dict):
            new_blocks.append(b)
    msg.content = new_blocks if new_blocks else ""


def _convert_thinking_blocks(
    messages: list[Message], source_provider: str | None, target_provider: str
) -> list[Message]:
    """Convert thinking blocks to plain text when switching provider families."""
    if _same_family(source_provider, target_provider):
        return messages
    if not any(b.get("type") == "thinking" for b in _iter_blocks(messages)):
        return messages
    for msg in messages:
        _rewrite_message_blocks(msg)
    return messages
