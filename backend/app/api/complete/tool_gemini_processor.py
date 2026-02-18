"""Gemini-specific event processing for tool execution."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from .tool_progress import ProgressTracker

logger = logging.getLogger(__name__)


def _process_text_block(block: Any, content_parts: list[str]) -> None:
    """Append text from a text block to content_parts if non-empty."""
    text = getattr(block, "text", "")
    if text:
        content_parts.append(text)


async def _process_tool_use_block(
    block: Any,
    turn: int,
    session_id: str,
    db: AsyncSession,
    tracker: ProgressTracker,
    model_used: str | None,
    agent_id: str | None,
) -> int:
    """Store and report a single tool_use block; returns 1 (increment)."""
    from .tool_event_storage import store_tool_use

    tool_name = getattr(block, "name", "unknown")
    tool_input = getattr(block, "input", {})
    await store_tool_use(db, session_id, tool_name, tool_input, model_used=model_used, agent_id=agent_id)
    await tracker.report_tool_use(turn, tool_name, tool_input)
    return 1


async def _process_assistant_block(
    block: Any,
    turn: int,
    session_id: str,
    db: AsyncSession,
    content_parts: list[str],
    tracker: ProgressTracker,
    model_used: str | None,
    agent_id: str | None,
) -> int:
    """Process a single content block from an assistant message.

    Returns the number of tool calls made (0 or 1).
    """
    block_type = getattr(block, "type", None)
    if block_type == "text":
        _process_text_block(block, content_parts)
        return 0
    if block_type == "tool_use":
        return await _process_tool_use_block(
            block, turn, session_id, db, tracker, model_used, agent_id
        )
    return 0


async def _process_assistant_event(
    event: Any,
    turn: int,
    session_id: str,
    db: AsyncSession,
    content_parts: list[str],
    tracker: ProgressTracker,
    model_used: str | None,
    agent_id: str | None,
) -> int:
    """Process an assistant event; returns total tool_calls_increment."""
    message = getattr(event, "message", None)
    if not message:
        return 0
    tool_calls_increment = 0
    for block in getattr(message, "content", []):
        tool_calls_increment += await _process_assistant_block(
            block, turn, session_id, db, content_parts, tracker, model_used, agent_id
        )
    return tool_calls_increment


async def _process_tool_result_event(
    event: Any,
    turn: int,
    session_id: str,
    db: AsyncSession,
    model_used: str | None,
    agent_id: str | None,
) -> int:
    """Store a tool_result event and return the incremented turn."""
    from .tool_event_storage import store_tool_result

    tool_content = getattr(event, "content", "")
    tool_use_id = getattr(event, "tool_use_id", "")
    is_error = getattr(event, "is_error", False)
    duration_ms = getattr(event, "duration_ms", None)
    await store_tool_result(
        db, session_id, tool_use_id, tool_content, is_error,
        duration_ms=duration_ms,
        agent_id=agent_id, model_used=model_used,
    )
    return turn + 1


def _process_result_event(event: Any, content_parts: list[str]) -> None:
    """Append result text to content_parts if it is not already present."""
    result_text = getattr(event, "result", "")
    if result_text and result_text not in "".join(content_parts):
        content_parts.append(result_text)


def _process_error_event(event: Any) -> str:
    """Log and return the error message from an error event."""
    error_message = getattr(event, "error", "Unknown error")
    logger.error(f"Gemini tool execution error: {error_message}")
    return error_message


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
    event_type = getattr(event, "type", None)
    tool_calls_increment = 0
    error_message = None

    if event_type == "assistant":
        tool_calls_increment = await _process_assistant_event(
            event, turn, session_id, db, content_parts, tracker, model_used, agent_id
        )
    elif event_type == "tool_result":
        turn = await _process_tool_result_event(
            event, turn, session_id, db, model_used, agent_id
        )
    elif event_type == "result":
        _process_result_event(event, content_parts)
    elif event_type == "error":
        error_message = _process_error_event(event)

    return turn, tool_calls_increment, error_message
