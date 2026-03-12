"""Unified event processing for tool execution across all providers.

Replaces the separate tool_claude_processor.py and tool_gemini_processor.py
with a single processor that handles ToolEvent objects regardless of source.
Claude SDK messages and OpenAI StreamEvents are converted to ToolEvent by
their respective adapters before reaching this processor.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.services.session_health import (
    executing_tool_health_detail,
    update_session_health,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from .tool_progress import ProgressTracker

logger = logging.getLogger(__name__)


def _process_text_block(block: Any, content_parts: list[str]) -> None:
    """Append text from a text block to content_parts if non-empty."""
    text = getattr(block, "text", "")
    if text:
        content_parts.append(text)


async def _process_thinking_block(
    block: Any,
    thinking_parts: list[str],
    db: AsyncSession,
    session_id: str,
    model_used: str | None,
    agent_id: str | None,
) -> None:
    """Store thinking event to DB immediately and append to thinking_parts.

    Note: Token estimation (len(text) // 4) is a rough approximation assuming
    ~4 characters per token. This may be inaccurate for code, non-Latin scripts,
    or whitespace-heavy content. Intended for observability/estimates only, not
    for precise token counting.
    """
    from .tool_event_storage import store_thinking_event

    text = getattr(block, "text", "")
    if text and text not in thinking_parts:
        thinking_parts.append(text)
        await store_thinking_event(
            db=db,
            session_id=session_id,
            thinking_content=text,
            tokens=len(text) // 4,
            model_used=model_used,
            agent_id=agent_id,
        )


async def _process_tool_use_block(
    block: Any,
    turn: int,
    session_id: str,
    db: AsyncSession,
    tracker: ProgressTracker,
    model_used: str | None,
    agent_id: str | None,
    tool_use_id_to_name: dict[str, str] | None = None,
) -> int:
    """Store and report a tool_use block; returns 1 (increment)."""
    from .tool_event_storage import store_tool_use

    tool_name = getattr(block, "name", "unknown")
    tool_input = getattr(block, "input", {})
    tool_use_id = getattr(block, "id", "")

    # Track tool_use_id → tool_name so tool_result events can resolve the name
    if tool_use_id and tool_use_id_to_name is not None:
        tool_use_id_to_name[tool_use_id] = tool_name

    await update_session_health(
        db,
        session_id,
        executing_tool_health_detail(tool_name),
        commit=True,
    )
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
    tool_use_id_to_name: dict[str, str] | None = None,
) -> int:
    """Process an assistant event; returns total tool_calls_increment."""
    message = getattr(event, "message", None)
    if not message:
        return 0
    await update_session_health(db, session_id, "processing_response", commit=True)
    tool_calls_increment = 0
    for block in getattr(message, "content", []):
        block_type = getattr(block, "type", None)
        if block_type == "text":
            _process_text_block(block, content_parts)
        elif block_type == "thinking":
            await _process_thinking_block(
                block, thinking_parts, db, session_id, model_used, agent_id,
            )
        elif block_type == "tool_use":
            tool_calls_increment += await _process_tool_use_block(
                block, turn, session_id, db, tracker, model_used, agent_id,
                tool_use_id_to_name=tool_use_id_to_name,
            )
    return tool_calls_increment


async def _process_tool_result_event(
    event: Any,
    turn: int,
    session_id: str,
    db: AsyncSession,
    model_used: str | None,
    agent_id: str | None,
    tool_use_id_to_name: dict[str, str] | None = None,
    tool_result_summaries: list[str] | None = None,
) -> int:
    """Store a tool_result event and return the incremented turn."""
    from .tool_event_storage import store_tool_result

    tool_content = getattr(event, "content", "")
    tool_use_id = getattr(event, "tool_use_id", "")
    is_error = getattr(event, "is_error", False)
    duration_ms = getattr(event, "duration_ms", None)

    # Resolve actual tool name from the tool_use_id mapping
    tool_name = (tool_use_id_to_name or {}).get(tool_use_id, tool_use_id)
    if tool_result_summaries is not None:
        summary = _summarize_tool_result(tool_name, tool_content, is_error)
        if summary:
            tool_result_summaries.append(summary)

    await store_tool_result(
        db, session_id, tool_name=tool_name, tool_use_id=tool_use_id,
        content=tool_content, is_error=is_error,
        duration_ms=duration_ms, agent_id=agent_id, model_used=model_used,
    )
    await update_session_health(db, session_id, "processing_response", commit=True)
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
    tool_use_id_to_name: dict[str, str] | None = None,
    tool_result_summaries: list[str] | None = None,
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
        tool_use_id_to_name: Mutable mapping of tool_use_id to tool_name,
            populated by tool_use events and consumed by tool_result events.
            Caller should pass a shared dict across calls.

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
            tool_use_id_to_name=tool_use_id_to_name,
        )
    elif event_type == "tool_result":
        turn = await _process_tool_result_event(
            event, turn, session_id, db, model_used, agent_id,
            tool_use_id_to_name=tool_use_id_to_name,
            tool_result_summaries=tool_result_summaries,
        )
    elif event_type == "result":
        _process_result_event(event, content_parts)
    elif event_type == "error":
        error_message = _process_error_event(event)

    return turn, tool_calls_increment, error_message


def _summarize_tool_result(tool_name: str, content: str, is_error: bool) -> str | None:
    """Build a compact one-line summary from a tool result."""
    first_line = next((line.strip() for line in str(content).splitlines() if line.strip()), "")
    if not first_line:
        first_line = "<no output>"
    prefix = f"{tool_name or 'tool'}"
    if is_error:
        prefix = f"{prefix} error"
    return f"{prefix}: {first_line[:160]}"
