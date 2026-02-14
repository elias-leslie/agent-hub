"""Gemini-specific event processing for tool execution."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from .tool_progress import ProgressTracker

logger = logging.getLogger(__name__)


async def process_gemini_event(
    event: Any,
    turn: int,
    session_id: str,
    db: AsyncSession,
    content_parts: list[str],
    tracker: ProgressTracker,
    model_used: str | None = None,
    agent_id: str | None = None,
) -> tuple[int, int, str | None]:
    """Process a single Gemini event and extract content/tool calls.

    Args:
        event: Event from Gemini SDK
        turn: Current turn number
        session_id: Session ID for storage
        db: Database session
        content_parts: List to append text content to
        tracker: Progress tracker instance
        model_used: Model identifier for event attribution
        agent_id: Agent slug for event attribution

    Returns:
        Tuple of (updated_turn, tool_calls_increment, error_message)
        error_message is set if event indicates an error
    """
    from .tool_event_storage import store_tool_result, store_tool_use

    event_type = getattr(event, "type", None)
    tool_calls_increment = 0
    error_message = None

    # Process assistant messages
    if event_type == "assistant":
        message = getattr(event, "message", None)
        if message:
            for block in getattr(message, "content", []):
                block_type = getattr(block, "type", None)
                if block_type == "text":
                    text = getattr(block, "text", "")
                    if text:
                        content_parts.append(text)
                elif block_type == "tool_use":
                    tool_calls_increment += 1
                    tool_name = getattr(block, "name", "unknown")
                    tool_input = getattr(block, "input", {})
                    await store_tool_use(db, session_id, tool_name, tool_input, model_used=model_used, agent_id=agent_id)
                    await tracker.report_tool_use(turn, tool_name, tool_input)

    # Process tool_result events
    elif event_type == "tool_result":
        tool_content = getattr(event, "content", "")
        tool_use_id = getattr(event, "tool_use_id", "")
        is_error = getattr(event, "is_error", False)
        await store_tool_result(db, session_id, tool_use_id, tool_content, is_error, agent_id=agent_id)
        turn += 1

    # Process result event
    elif event_type == "result":
        result_text = getattr(event, "result", "")
        if result_text and result_text not in "".join(content_parts):
            content_parts.append(result_text)

    # Process error event
    elif event_type == "error":
        error_message = getattr(event, "error", "Unknown error")
        logger.error(f"Gemini tool execution error: {error_message}")

    return turn, tool_calls_increment, error_message
