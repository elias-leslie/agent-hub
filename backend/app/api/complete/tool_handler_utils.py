"""Shared utilities and helper functions for tool execution handlers."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.adapters.base import Message
from app.models import Session as DBSession
from app.services.session_health import health_detail_for_error, update_session_health

from .closeout_policy import detached_agent_hub_rebuild_closeout
from .tool_event_processor import process_tool_event
from .tool_models import ToolExecutionResult
from .tool_progress import ProgressTracker
from .tool_result_builder import build_error_result
from .turn_budget import resolve_tool_max_turns

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["_ExecutionState", "_init_execution_state", "_run_tool_loop"]


def _extract_tool_metadata(
    tool_use_metadata: dict[str, dict[str, Any]],
    tool_use_id: str | None,
) -> tuple[str, dict[str, Any]]:
    """Return the resolved tool name and original tool input for a tool_result."""
    metadata = tool_use_metadata.get(tool_use_id or "", {})
    tool_name = str(metadata.get("name") or tool_use_id or "unknown")
    tool_input = metadata.get("input")
    return tool_name, tool_input if isinstance(tool_input, dict) else {}


@dataclass
class _ExecutionState:
    """Shared mutable state for a tool execution run."""

    agent_slug: str | None
    messages_for_adapter: list[Message]
    external_id: str | None = None
    requires_progress_tags: bool = False
    content_parts: list[str] = field(default_factory=list)
    thinking_parts: list[str] = field(default_factory=list)
    tool_result_summaries: list[str] = field(default_factory=list)
    tool_calls_count: int = 0
    turn: int = 0
    event_turn: int = 0
    awaiting_tool_results: bool = False
    terminal_finish_reason: str | None = None


def _init_execution_state(
    session: DBSession,
    messages: list[dict[str, Any]],
) -> _ExecutionState:
    """Build shared execution state from session and raw messages."""
    agent_slug = getattr(session, "agent_slug", None)
    external_id = getattr(session, "external_id", None)
    messages_for_adapter = [Message(role=m["role"], content=m["content"]) for m in messages]
    return _ExecutionState(
        agent_slug=agent_slug,
        external_id=external_id,
        requires_progress_tags=bool(
            external_id and str(external_id).startswith("task-")
        ),
        messages_for_adapter=messages_for_adapter,
    )


def _check_result_event(event: Any, state: _ExecutionState) -> None:
    """Update terminal_finish_reason when a result event is received."""
    state.terminal_finish_reason = getattr(event, "finish_reason", None) or "end_turn"


def _check_tool_result_event(
    event: Any,
    state: _ExecutionState,
    tool_use_metadata: dict[str, dict[str, Any]],
    project_id: str | None,
) -> bool:
    """Handle a tool_result event; return True if the loop should break."""
    tool_name, tool_input = _extract_tool_metadata(
        tool_use_metadata,
        getattr(event, "tool_use_id", None),
    )
    detached_closeout = detached_agent_hub_rebuild_closeout(
        project_id=project_id,
        tool_name=tool_name,
        tool_input=tool_input,
        tool_content=str(getattr(event, "content", "") or ""),
        agent_slug=state.agent_slug,
        external_id=state.external_id,
    )
    if detached_closeout is not None:
        state.content_parts = [detached_closeout]
        state.terminal_finish_reason = "end_turn"
        return True
    return False


async def _process_event(
    event: Any,
    state: _ExecutionState,
    tool_use_metadata: dict[str, dict[str, Any]],
    session_id: str,
    db: AsyncSession,
    tracker: ProgressTracker,
    model: str,
    project_id: str | None,
    terminal_error_message: str | None,
) -> tuple[str | None, bool]:
    """Process a single event; return (updated terminal_error_message, should_break)."""
    (
        state.event_turn,
        tools_delta,
        error_message,
        state.turn,
        state.awaiting_tool_results,
    ) = await process_tool_event(
        event, state.event_turn, state.turn, state.awaiting_tool_results, session_id, db,
        state.content_parts, state.thinking_parts, tracker, model_used=model,
        agent_id=state.agent_slug, requires_progress_tags=state.requires_progress_tags,
        tool_use_id_to_name=tool_use_metadata,
        tool_result_summaries=state.tool_result_summaries,
    )
    state.tool_calls_count += tools_delta

    event_type = getattr(event, "type", None)
    if event_type == "result":
        _check_result_event(event, state)
    elif event_type == "tool_result" and _check_tool_result_event(event, state, tool_use_metadata, project_id):
        return terminal_error_message, True

    if error_message and terminal_error_message is None:
        # Record the terminal error, but keep draining the provider stream so
        # SDK-backed generators can unwind cleanly on their own task boundary.
        terminal_error_message = error_message
        await update_session_health(
            db, session_id, health_detail_for_error(error_message), commit=True,
        )
    elif event_type == "tool_result":
        await update_session_health(db, session_id, "calling_model", commit=True)

    return terminal_error_message, False


async def _drain_event_stream(
    event_stream: Any,
    state: _ExecutionState,
    tool_use_metadata: dict[str, dict[str, Any]],
    session_id: str,
    db: AsyncSession,
    tracker: ProgressTracker,
    model: str,
    project_id: str | None,
) -> tuple[str | None, bool]:
    """Drain the event stream; return (terminal_error_message, exhausted)."""
    terminal_error_message: str | None = None
    exhausted = False
    async for event, _session_id in event_stream:
        terminal_error_message, should_break = await _process_event(
            event, state, tool_use_metadata, session_id, db, tracker, model,
            project_id, terminal_error_message,
        )
        if should_break:
            break
    else:
        exhausted = True
    return terminal_error_message, exhausted


async def _execute_event_stream(
    runtime_session: Any,
    state: _ExecutionState,
    session_id: str,
    db: AsyncSession,
    tracker: ProgressTracker,
    model: str,
    project_id: str | None,
) -> tuple[str | None, bool]:
    """Run the event stream with cancellation handling; return (error_msg, exhausted)."""
    event_stream = runtime_session.events()
    tool_use_metadata: dict[str, dict[str, Any]] = {}
    terminal_error_message: str | None = None
    exhausted = False
    try:
        terminal_error_message, exhausted = await _drain_event_stream(
            event_stream, state, tool_use_metadata, session_id, db, tracker, model, project_id,
        )
    except asyncio.CancelledError:
        with suppress(Exception):
            await runtime_session.interrupt()
        raise
    finally:
        # Only force-close provider streams when the loop exits early. Redundant
        # close after natural exhaustion can re-enter provider cleanup on a
        # foreign task and inject cancellation into the caller.
        if not exhausted:
            await runtime_session.close()
    return terminal_error_message, exhausted


async def _run_tool_loop(
    adapter: Any,
    state: _ExecutionState,
    provider: str,
    model: str,
    tools: list[dict[str, Any]] | None,
    tool_catalog: list[dict[str, Any]] | None,
    working_dir: str | None,
    session_id: str,
    loaded_memory_uuids: list[str],
    db: AsyncSession,
    tracker: ProgressTracker,
    max_turns: int = 1,
    project_id: str | None = None,
) -> ToolExecutionResult | None:
    """Unified tool loop for all providers.

    Streams events from the adapter's complete_with_tools(), converting
    provider-specific events to ToolEvent format, then processing each
    through the unified tool_event_processor.

    Returns an error result on failure, else None (results in state).
    """
    await update_session_health(db, session_id, "calling_model", commit=True)
    runtime_session = await adapter.start_tool_session(
        messages=state.messages_for_adapter,
        model=model,
        tools=tools,
        tool_catalog=tool_catalog,
        working_dir=working_dir,
        max_turns=resolve_tool_max_turns(provider, max_turns),
        project_id=project_id,
        session_id=session_id,
        agent_slug=state.agent_slug,
    )
    terminal_error_message, _ = await _execute_event_stream(
        runtime_session, state, session_id, db, tracker, model, project_id,
    )
    if terminal_error_message:
        return build_error_result(
            Exception(terminal_error_message), model, provider, session_id, loaded_memory_uuids,
            turns=state.turn, tool_calls_count=state.tool_calls_count,
        )
    return None
