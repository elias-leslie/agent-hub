"""Claude-specific message processing for tool execution."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from claude_agent_sdk.types import AssistantMessage, TextBlock, UserMessage

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from .tool_progress import ProgressTracker


def _is_thinking_block(msg: Any) -> bool:
    """Return True if msg is a thinking block."""
    return type(msg).__name__ == "ThinkingBlock" or (
        hasattr(msg, "type") and msg.type == "thinking"
    )


def _is_tool_use_block(msg: Any) -> bool:
    """Return True if msg is a tool use block."""
    return type(msg).__name__ == "ToolUseBlock" or (
        hasattr(msg, "type") and msg.type == "tool_use"
    )


def _extract_thinking_text(msg: Any) -> str:
    """Extract thinking text from a thinking block."""
    return getattr(msg, "thinking", "") or getattr(msg, "text", "")


async def _handle_tool_use(
    block: Any,
    turn: int,
    session_id: str,
    db: AsyncSession,
    tracker: ProgressTracker,
    model_used: str | None,
    agent_id: str | None,
) -> None:
    """Store tool use event and report progress."""
    from .tool_event_storage import store_tool_use

    tool_name = getattr(block, "name", "unknown")
    tool_input = getattr(block, "input", {})
    await store_tool_use(db, session_id, tool_name, tool_input, model_used=model_used, agent_id=agent_id)
    await tracker.report_tool_use(turn, tool_name, tool_input)


async def _process_assistant_blocks(
    msg: AssistantMessage,
    turn: int,
    session_id: str,
    db: AsyncSession,
    content_parts: list[str],
    thinking_parts: list[str],
    tracker: ProgressTracker,
    model_used: str | None,
    agent_id: str | None,
) -> int:
    """Process content blocks inside an AssistantMessage. Returns tool_calls_increment."""
    tool_calls_increment = 0
    for block in msg.content:
        if isinstance(block, TextBlock):
            content_parts.append(block.text)
        if _is_thinking_block(block):
            thinking_text = _extract_thinking_text(block)
            if thinking_text and thinking_text not in thinking_parts:
                thinking_parts.append(thinking_text)
        if _is_tool_use_block(block):
            tool_calls_increment += 1
            await _handle_tool_use(block, turn, session_id, db, tracker, model_used, agent_id)
    return tool_calls_increment


async def _process_user_message(
    msg: UserMessage,
    session_id: str,
    db: AsyncSession,
    agent_id: str | None,
    model_used: str | None,
) -> None:
    """Process tool result blocks inside a UserMessage."""
    from .tool_event_storage import store_tool_result

    if not hasattr(msg, "content"):
        return
    for block in msg.content:
        if type(block).__name__ != "ToolResultBlock":
            continue
        result_content = getattr(block, "content", "")
        is_error = getattr(block, "is_error", False)
        tool_use_id = getattr(block, "tool_use_id", "")
        await store_tool_result(
            db, session_id, tool_use_id, result_content, is_error,
            agent_id=agent_id, model_used=model_used,
        )


async def process_claude_message(
    msg: Any,
    turn: int,
    session_id: str,
    db: AsyncSession,
    content_parts: list[str],
    thinking_parts: list[str],
    tracker: ProgressTracker,
    model_used: str | None = None,
    agent_id: str | None = None,
) -> tuple[int, int]:
    """Process a single Claude message; extract content/thinking/tool calls.

    Returns:
        Tuple of (updated_turn, tool_calls_increment)
    """
    tool_calls_increment = 0

    # Extract thinking blocks
    if _is_thinking_block(msg):
        thinking_text = _extract_thinking_text(msg)
        if thinking_text:
            thinking_parts.append(thinking_text)

    # Track top-level tool use
    if _is_tool_use_block(msg):
        tool_calls_increment += 1
        await _handle_tool_use(msg, turn, session_id, db, tracker, model_used, agent_id)

    # Extract text content and nested blocks from AssistantMessage
    if isinstance(msg, AssistantMessage):
        turn += 1
        tool_calls_increment += await _process_assistant_blocks(
            msg, turn, session_id, db, content_parts, thinking_parts, tracker, model_used, agent_id,
        )

    # Handle UserMessage (contains tool results from SDK)
    if isinstance(msg, UserMessage):
        await _process_user_message(msg, session_id, db, agent_id, model_used)

    return turn, tool_calls_increment
