"""Unified event processing for tool execution across all providers.

Replaces the separate tool_claude_processor.py and tool_gemini_processor.py
with a single processor that handles ToolEvent objects regardless of source.
Claude SDK messages and OpenAI StreamEvents are converted to ToolEvent by
their respective adapters before reaching this processor.
"""

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


def _process_thinking_block(block: Any, thinking_parts: list[str]) -> None:
    """Append thinking text from a thinking block if non-empty and unique."""
    text = getattr(block, "text", "")
    if text and text not in thinking_parts:
        thinking_parts.append(text)


async def _process_tool_use_block(
    block: Any,
    turn: int,
    session_id: str,
    db: AsyncSession,
    tracker: ProgressTracker,
    model_used: str | None,
    agent_id: str | None,
) -> int:
    """Store and report a tool_use block; returns 1 (increment)."""
    from .tool_event_storage import store_tool_use

    tool_name = getattr(block, "name", "unknown")
    tool_input = getattr(block, "input", {})
    await store_tool_use(db, session_id, tool_name, tool_input, model_used=model_used, agent_id=agent_id)
    await tracker.report_tool_use(turn, tool_name, tool_input)
    return 1


async def _process_assistant_event(
    event: Any,
    turn: int,
    session_id: str,
    db: AsyncSession,
    content_parts: list[str],
    thinking_parts: list[str],
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
        block_type = getattr(block, "type", None)
        if block_type == "text":
            _process_text_block(block, content_parts)
        elif block_type == "thinking":
            _process_thinking_block(block, thinking_parts)
        elif block_type == "tool_use":
            tool_calls_increment += await _process_tool_use_block(
                block, turn, session_id, db, tracker, model_used, agent_id
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
        duration_ms=duration_ms, agent_id=agent_id, model_used=model_used,
    )
    return turn + 1


def _process_result_event(event: Any, content_parts: list[str]) -> None:
    """Append result text to content_parts if not already present."""
    result_text = getattr(event, "result", "")
    if result_text and result_text not in "".join(content_parts):
        content_parts.append(result_text)


def _process_error_event(event: Any) -> str:
    """Log and return the error message from an error event."""
    error_message = getattr(event, "error", "Unknown error")
    logger.error(f"Tool execution error: {error_message}")
    return error_message


async def process_tool_event(
    event: Any,
    turn: int,
    session_id: str,
    db: AsyncSession,
    content_parts: list[str],
    thinking_parts: list[str],
    tracker: ProgressTracker,
    model_used: str | None = None,
    agent_id: str | None = None,
) -> tuple[int, int, str | None]:
    """Process a single unified ToolEvent.

    Handles all event types: assistant, tool_result, result, error.
    Works identically for Claude, Gemini, CloudCode, and OpenAI-compat events
    once they've been adapted to ToolEvent format.

    Args:
        event: ToolEvent from any provider's event adapter
        turn: Current turn number
        session_id: Session ID for storage
        db: Database session
        content_parts: List to append text content to
        thinking_parts: List to append thinking content to
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
            event, turn, session_id, db, content_parts, thinking_parts,
            tracker, model_used, agent_id,
        )
    elif event_type == "tool_result":
        turn = await _process_tool_result_event(
            event, turn, session_id, db, model_used, agent_id,
        )
    elif event_type == "result":
        _process_result_event(event, content_parts)
    elif event_type == "error":
        error_message = _process_error_event(event)

    return turn, tool_calls_increment, error_message
