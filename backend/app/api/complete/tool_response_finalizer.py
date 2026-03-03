"""Unified response finalization for tool execution handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models import Session as DBSession

    from .tool_models import ToolExecutionResult
    from .tool_progress import ProgressTracker


async def finalize_response(
    db: AsyncSession,
    session: DBSession,
    session_id: str,
    is_new_session: bool,
    model: str,
    provider: str,
    content_parts: list[str],
    thinking_parts: list[str],
    loaded_memory_uuids: list[str],
    memory_group_id: str | None,
    turn: int,
    tool_calls_count: int,
    tracker: ProgressTracker,
) -> ToolExecutionResult:
    """Finalize response with optional thinking content support.

    Works for all providers. Thinking content is included when present
    (e.g., Claude with extended thinking), omitted otherwise.

    Args:
        db: Database session
        session: DB session model
        session_id: Session ID
        is_new_session: Whether this is a new session
        model: Model name
        provider: Provider name
        content_parts: List of content strings
        thinking_parts: List of thinking strings (may be empty)
        loaded_memory_uuids: UUIDs of loaded memory
        memory_group_id: Memory group ID
        turn: Final turn count
        tool_calls_count: Total tool calls count
        tracker: Progress tracker

    Returns:
        ToolExecutionResult with response data
    """
    from .tool_event_storage import store_assistant_response
    from .tool_result_builder import finalize_result

    agent_slug = getattr(session, "agent_slug", None)
    final_content = "".join(content_parts)
    thinking_content = "\n".join(thinking_parts) if thinking_parts else None
    thinking_tokens = len(thinking_content) // 4 if thinking_content else None
    estimated_tokens = len(final_content) // 4

    await store_assistant_response(
        db, session_id, final_content, model, estimated_tokens,
        agent_id=agent_slug,
    )
    await tracker.report_complete(turn or 1, tool_calls_count)

    return await finalize_result(
        db=db,
        session=session,
        session_id=session_id,
        is_new_session=is_new_session,
        model=model,
        provider=provider,
        content=final_content,
        loaded_memory_uuids=loaded_memory_uuids,
        memory_group_id=memory_group_id,
        thinking_content=thinking_content,
        thinking_tokens=thinking_tokens,
        turn=turn or 1,
        tool_calls_count=tool_calls_count,
        progress_log=tracker.log,
    )
