"""Message and SSE formatting helpers for the streaming tool loop."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .schemas import StreamingChunk
from .streaming_context import StreamContext

if TYPE_CHECKING:
    from app.adapters.types import StreamEvent


def build_assistant_content_blocks(
    text_content: str,
    tool_calls: list[StreamEvent],
) -> list[dict[str, object]]:
    """Build Anthropic-format content blocks for an assistant message.

    Preserves ``thought_signature`` so CloudCode PA can validate
    thinking-enabled function calls on subsequent turns.
    """
    blocks: list[dict[str, object]] = []
    if text_content:
        blocks.append({"type": "text", "text": text_content})
    for tc in tool_calls:
        block: dict[str, object] = {
            "type": "tool_use",
            "id": tc.tool_id,
            "name": tc.tool_name,
            "input": tc.tool_input or {},
        }
        if tc.thought_signature:
            block["thought_signature"] = tc.thought_signature
        blocks.append(block)
    return blocks


def build_tool_result_blocks(
    results: list[tuple[str, str, str, bool]],
) -> list[dict[str, object]]:
    """Build tool_result content blocks for a user message.

    Args:
        results: List of (tool_use_id, tool_name, content, is_error) tuples.
    """
    blocks: list[dict[str, object]] = []
    for tool_use_id, tool_name, content, is_error in results:
        block: dict[str, object] = {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "tool_name": tool_name,
            "content": content,
        }
        if is_error:
            block["is_error"] = True
        blocks.append(block)
    return blocks


def sse_for_simple_event(
    event: object,
    content_buf: list[str],
    ctx: StreamContext,
) -> str | None:
    """Return SSE string for content/tool_use/tool_result/error events; None otherwise."""
    event_type = getattr(event, "type", None)
    if event_type == "content":
        content_buf[0] += getattr(event, "content", None) or ""
        chunk = StreamingChunk(
            type="content", seq=ctx.next_seq(), content=getattr(event, "content", None)
        )
        return f"data: {chunk.model_dump_json()}\n\n"
    if event_type == "tool_use":
        chunk = StreamingChunk(
            type="tool_use",
            seq=ctx.next_seq(),
            tool_id=getattr(event, "tool_id", None),
            tool_name=getattr(event, "tool_name", None),
            tool_input=getattr(event, "tool_input", None),
        )
        return f"data: {chunk.model_dump_json()}\n\n"
    if event_type == "tool_result":
        chunk = StreamingChunk(
            type="tool_result",
            seq=ctx.next_seq(),
            tool_id=getattr(event, "tool_id", None),
            tool_result=getattr(event, "content", None),
            tool_status="complete",
        )
        return f"data: {chunk.model_dump_json()}\n\n"
    if event_type == "thinking":
        chunk = StreamingChunk(
            type="thinking", seq=ctx.next_seq(), content=getattr(event, "content", None)
        )
        return f"data: {chunk.model_dump_json()}\n\n"
    if event_type == "error":
        error_chunk = StreamingChunk(
            type="error", seq=ctx.next_seq(), error=getattr(event, "error", None)
        )
        return f"data: {error_chunk.model_dump_json()}\n\n"
    return None
