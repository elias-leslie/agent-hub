"""Claude-specific message processing for tool execution."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from claude_agent_sdk.types import AssistantMessage, TextBlock, UserMessage

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from .tool_progress import ProgressTracker


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
    """Process a single Claude message and extract content/thinking/tool calls.

    Args:
        msg: Message from Claude SDK
        turn: Current turn number
        session_id: Session ID for storage
        db: Database session
        content_parts: List to append text content to
        thinking_parts: List to append thinking content to
        tracker: Progress tracker instance
        model_used: Model identifier for event attribution
        agent_id: Agent slug for event attribution

    Returns:
        Tuple of (updated_turn, tool_calls_increment)
    """
    from .tool_event_storage import store_tool_result, store_tool_use

    msg_type = type(msg).__name__
    tool_calls_increment = 0

    # Extract thinking blocks
    if msg_type == "ThinkingBlock" or (hasattr(msg, "type") and msg.type == "thinking"):
        thinking_text = getattr(msg, "thinking", "") or getattr(msg, "text", "")
        if thinking_text:
            thinking_parts.append(thinking_text)

    # Track tool use
    if msg_type == "ToolUseBlock" or (hasattr(msg, "type") and msg.type == "tool_use"):
        tool_calls_increment += 1
        tool_name = getattr(msg, "name", "unknown")
        tool_input = getattr(msg, "input", {})
        await store_tool_use(db, session_id, tool_name, tool_input, model_used=model_used, agent_id=agent_id)
        await tracker.report_tool_use(turn, tool_name, tool_input)

    # Extract text content from AssistantMessage
    if isinstance(msg, AssistantMessage):
        turn += 1
        for block in msg.content:
            if isinstance(block, TextBlock):
                content_parts.append(block.text)
            block_type = type(block).__name__
            if block_type == "ThinkingBlock" or getattr(block, "type", "") == "thinking":
                thinking_text = getattr(block, "thinking", "") or getattr(block, "text", "")
                if thinking_text and thinking_text not in thinking_parts:
                    thinking_parts.append(thinking_text)
            # Check for ToolUseBlock inside AssistantMessage
            if block_type == "ToolUseBlock" or getattr(block, "type", "") == "tool_use":
                tool_calls_increment += 1
                tool_name = getattr(block, "name", "unknown")
                tool_input = getattr(block, "input", {})
                await store_tool_use(db, session_id, tool_name, tool_input, model_used=model_used, agent_id=agent_id)
                await tracker.report_tool_use(turn, tool_name, tool_input)

    # Handle UserMessage (contains tool results from SDK)
    if isinstance(msg, UserMessage) and hasattr(msg, "content"):
        for block in msg.content:  # type: ignore[assignment]
            block_type = type(block).__name__
            if block_type == "ToolResultBlock":
                result_content = getattr(block, "content", "")
                is_error = getattr(block, "is_error", False)
                tool_use_id = getattr(block, "tool_use_id", "")
                await store_tool_result(db, session_id, tool_use_id, result_content, is_error, agent_id=agent_id)

    return turn, tool_calls_increment
