"""Unified event processing for tool execution across all providers.

Replaces the separate tool_claude_processor.py and tool_gemini_processor.py
with a single processor that handles ToolEvent objects regardless of source.
Provider adapters normalize provider-native runtime output to ToolEvent before
reaching this processor.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.services.narration_tags import parse_narration_tags
from app.services.session_health import (
    executing_tool_health_detail,
    progress_tag_health_detail,
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


async def _extract_narration_from_text(
    text: str, db: AsyncSession, session_id: str,
) -> None:
    """Extract narration tags from intermediate text blocks during tool loops.

    The normal narration pipeline only fires on stored assistant_message events,
    but during multi-turn tool execution, text blocks are accumulated without
    being stored as events. This extracts P tags inline so they aren't lost.
    """
    if "[[P:" not in text:
        return
    try:
        from app.models import SessionEventType
        from app.services.narration_extraction import extract_narration_from_event

        await extract_narration_from_event(
            db,
            session_id=session_id,
            event_type=SessionEventType.ASSISTANT_MESSAGE,
            content=text,
        )
    except Exception:
        logger.debug("Failed to extract narration from tool-loop text", exc_info=True)


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
    tool_use_id_to_name: dict[str, dict[str, Any]] | None = None,
) -> int:
    """Store and report a tool_use block; returns 1 (increment)."""
    from .tool_event_storage import store_tool_use

    tool_name = getattr(block, "name", "unknown")
    tool_input = getattr(block, "input", {})
    tool_use_id = getattr(block, "id", "")

    if tool_use_id and tool_use_id_to_name is not None:
        tool_use_id_to_name[tool_use_id] = {"name": tool_name, "input": tool_input}

    await update_session_health(db, session_id, executing_tool_health_detail(tool_name), commit=True)
    await store_tool_use(db, session_id, tool_name, tool_input, model_used=model_used, agent_id=agent_id)
    await tracker.report_tool_use(turn, tool_name, tool_input)
    return 1


async def _handle_text_block(
    block: Any,
    session_id: str,
    db: AsyncSession,
    content_parts: list[str],
) -> bool:
    """Process a text block: append content, extract narration, return True if valid progress tag found."""
    _process_text_block(block, content_parts)
    text = getattr(block, "text", "")
    if not text:
        return False
    tags = parse_narration_tags(text)
    if "[[P:" in text:
        await _extract_narration_from_text(text, db, session_id)
    return bool(tags)


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
    requires_progress_tags: bool,
    tool_use_id_to_name: dict[str, dict[str, Any]] | None = None,
) -> int:
    """Process an assistant event; returns total tool_calls_increment."""
    message = getattr(event, "message", None)
    if not message:
        return 0
    await update_session_health(db, session_id, "processing_response", commit=True)
    tool_calls_increment = 0
    saw_text_block = False
    saw_valid_progress_tag = False
    for block in getattr(message, "content", []):
        block_type = getattr(block, "type", None)
        if block_type == "text":
            saw_text_block = True
            saw_valid_progress_tag |= await _handle_text_block(block, session_id, db, content_parts)
        elif block_type == "thinking":
            await _process_thinking_block(block, thinking_parts, db, session_id, model_used, agent_id)
        elif block_type == "tool_use":
            tool_calls_increment += await _process_tool_use_block(
                block, turn, session_id, db, tracker, model_used, agent_id,
                tool_use_id_to_name=tool_use_id_to_name,
            )
    if saw_text_block and requires_progress_tags:
        await update_session_health(
            db, session_id, progress_tag_health_detail(saw_valid_progress_tag), commit=True,
        )
    return tool_calls_increment


async def _process_tool_result_event(
    event: Any,
    turn: int,
    session_id: str,
    db: AsyncSession,
    model_used: str | None,
    agent_id: str | None,
    tracker: ProgressTracker,
    tool_use_id_to_name: dict[str, dict[str, Any]] | None = None,
    tool_result_summaries: list[str] | None = None,
) -> int:
    """Store a tool_result event and return the incremented turn."""
    from .tool_event_storage import store_tool_result

    tool_content = getattr(event, "content", "")
    tool_use_id = getattr(event, "tool_use_id", "")
    is_error = getattr(event, "is_error", False)
    duration_ms = getattr(event, "duration_ms", None)

    tool_metadata = (tool_use_id_to_name or {}).get(tool_use_id, {})
    tool_name = str(tool_metadata.get("name") or tool_use_id)
    tool_input = tool_metadata.get("input") if isinstance(tool_metadata.get("input"), dict) else None
    if tool_result_summaries is not None:
        summary = _summarize_tool_result(tool_name, tool_content, is_error)
        if summary:
            tool_result_summaries.append(summary)

    await store_tool_result(
        db, session_id, tool_name=tool_name, tool_use_id=tool_use_id,
        content=tool_content, is_error=is_error,
        duration_ms=duration_ms, agent_id=agent_id, model_used=model_used,
    )
    await tracker.report_tool_result(
        max(turn, 1),
        tool_name,
        is_error=is_error,
        tool_input=tool_input,
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


def _summarize_tool_result(tool_name: str, content: str, is_error: bool) -> str | None:
    """Build a compact one-line summary from a tool result."""
    first_line = next((line.strip() for line in str(content).splitlines() if line.strip()), "")
    if not first_line:
        first_line = "<no output>"
    prefix = f"{tool_name or 'tool'}"
    if is_error:
        prefix = f"{prefix} error"
    return f"{prefix}: {first_line[:160]}"


def _compute_assistant_turns(
    tool_calls_increment: int,
    model_turn: int,
    awaiting_tool_results: bool,
) -> tuple[int, bool]:
    """Update model_turn and awaiting_tool_results after an assistant event."""
    if tool_calls_increment > 0 and not awaiting_tool_results:
        model_turn += 1
    if tool_calls_increment > 0:
        awaiting_tool_results = True
    return model_turn, awaiting_tool_results


async def process_tool_event(
    event: Any, event_turn: int, model_turn: int, awaiting_tool_results: bool,
    session_id: str, db: AsyncSession, content_parts: list[str], thinking_parts: list[str],
    tracker: ProgressTracker, model_used: str | None = None, agent_id: str | None = None,
    requires_progress_tags: bool = False,
    tool_use_id_to_name: dict[str, dict[str, Any]] | None = None,
    tool_result_summaries: list[str] | None = None,
) -> tuple[int, int, str | None, int, bool]:
    """Process a single unified ToolEvent (assistant/tool_result/result/error).

    Returns (updated_event_turn, tool_calls_increment, error_message,
             updated_model_turn, updated_awaiting_tool_results).
    tool_use_id_to_name maps tool_use_id -> {name, input}; caller shares across calls.
    """
    event_type = getattr(event, "type", None)
    tool_calls_increment = 0
    error_message = None

    if event_type == "assistant":
        assistant_turn = model_turn if awaiting_tool_results and model_turn > 0 else model_turn + 1
        tool_calls_increment = await _process_assistant_event(
            event, assistant_turn, session_id, db, content_parts, thinking_parts,
            tracker, model_used, agent_id, requires_progress_tags,
            tool_use_id_to_name=tool_use_id_to_name,
        )
        model_turn, awaiting_tool_results = _compute_assistant_turns(
            tool_calls_increment, model_turn, awaiting_tool_results,
        )
    elif event_type == "tool_result":
        event_turn = await _process_tool_result_event(
            event, event_turn, session_id, db, model_used, agent_id, tracker,
            tool_use_id_to_name=tool_use_id_to_name,
            tool_result_summaries=tool_result_summaries,
        )
        awaiting_tool_results = False
    elif event_type == "result":
        _process_result_event(event, content_parts)
        if getattr(event, "finish_reason", None) != "max_turns":
            model_turn += 1
        awaiting_tool_results = False
    elif event_type == "error":
        error_message = _process_error_event(event)

    return event_turn, tool_calls_increment, error_message, model_turn, awaiting_tool_results
