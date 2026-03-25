"""Shared utilities and helper functions for tool execution handlers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.adapters.base import Message
from app.models import Session as DBSession
from app.services.session_health import health_detail_for_error, update_session_health

from .tool_event_processor import process_tool_event
from .tool_models import ToolExecutionResult
from .tool_progress import ProgressTracker
from .tool_result_builder import build_error_result
from .turn_budget import resolve_tool_max_turns

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["_ExecutionState", "_init_execution_state", "_run_tool_loop"]


def build_event_stream(
    adapter: Any,
    messages: list[Message],
    provider: str,
    model: str,
    tools: list[dict[str, Any]] | None,
    tool_catalog: list[dict[str, Any]] | None,
    working_dir: str | None,
    permission_config: dict[str, Any] | None,
    max_turns: int,
    project_id: str | None,
    session_id: str,
    agent_slug: str | None,
) -> Any:
    """Return the adapter-owned ToolEvent stream for a tool loop."""
    effective_max_turns = resolve_tool_max_turns(provider, max_turns)
    return adapter.complete_with_tool_events(
        messages=messages,
        model=model,
        tools=tools or [],
        working_dir=working_dir,
        permission_config=permission_config,
        max_turns=effective_max_turns,
        project_id=project_id,
        session_id=session_id,
        agent_slug=agent_slug,
        tool_catalog=tool_catalog,
    )


def _extract_tool_metadata(
    tool_use_metadata: dict[str, dict[str, Any]],
    tool_use_id: str | None,
) -> tuple[str, dict[str, Any]]:
    """Return the resolved tool name and original tool input for a tool_result."""
    metadata = tool_use_metadata.get(tool_use_id or "", {})
    tool_name = str(metadata.get("name") or tool_use_id or "unknown")
    tool_input = metadata.get("input")
    return tool_name, tool_input if isinstance(tool_input, dict) else {}


def _is_detached_agent_hub_rebuild_handoff(
    *,
    project_id: str | None,
    tool_name: str,
    tool_input: dict[str, Any],
    tool_content: str,
) -> bool:
    """Return True when a bash tool result queued a detached Agent Hub self-rebuild."""
    if project_id != "agent-hub" or tool_name.lower() != "bash":
        return False
    command = str(tool_input.get("command") or "").lower()
    if "agent-hub" not in command or "--detach" not in command:
        return False
    if "rebuild.sh" not in command and "restart.sh" not in command:
        return False
    output = tool_content.lower()
    return "detached rebuild queued" in output or "detached restart queued" in output


def _build_detached_agent_hub_rebuild_closeout(
    *,
    agent_slug: str | None,
    external_id: str | None,
    tool_content: str,
) -> str:
    """Return a deterministic closeout after queuing detached Agent Hub rebuild."""
    unit_line = next(
        (line.strip() for line in str(tool_content).splitlines() if "Running as unit:" in line),
        None,
    )
    unit_name = unit_line.removeprefix("Running as unit:").strip() if unit_line else None
    unit_note = f" as {unit_name}" if unit_name else ""
    if agent_slug == "persona":
        return (
            f"HEARTBEAT_ACTION — Detached Agent Hub rebuild queued{unit_note}. "
            "Post-restart verification is deferred to a fresh session.\n"
            "[[P:started:ending the heartbeat after queueing a detached Agent Hub rebuild]]\n"
            f"[[P:decision:queued detached Agent Hub rebuild{unit_note} and ended before "
            "post-restart verification]]\n"
            "[[S:partial:Queued detached Agent Hub rebuild; a fresh post-restart session "
            "must verify health and task completion.]]"
        )
    if external_id and str(external_id).startswith("task-"):
        return (
            f"Detached Agent Hub rebuild queued{unit_note}. "
            "This session is ending before post-restart verification.\n"
            "[[P:started:ending the task session after queueing a detached Agent Hub rebuild]]\n"
            f"[[P:decision:queued detached Agent Hub rebuild{unit_note} and ended before "
            "post-restart verification]]\n"
            "[[S:partial:Queued detached Agent Hub rebuild; a fresh post-restart session "
            "must verify health and task completion.]]"
        )
    if unit_line:
        return (
            "Detached Agent Hub rebuild queued successfully.\n"
            f"{unit_line}\n"
            "[[S:partial:Queued detached Agent Hub rebuild; a fresh post-restart session "
            "must verify health and task completion.]]"
        )
    return (
        "Detached Agent Hub rebuild queued successfully.\n"
        "[[S:partial:Queued detached Agent Hub rebuild; a fresh post-restart session "
        "must verify health and task completion.]]"
    )


@dataclass
class _ExecutionState:
    """Shared mutable state for a tool execution run."""

    agent_slug: str | None
    messages_for_adapter: list[Message]
    external_id: str | None = None
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
        messages_for_adapter=messages_for_adapter,
    )


async def _run_tool_loop(
    adapter: Any,
    state: _ExecutionState,
    provider: str,
    model: str,
    tools: list[dict[str, Any]] | None,
    tool_catalog: list[dict[str, Any]] | None,
    working_dir: str | None,
    permission_config: dict[str, Any] | None,
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

    event_stream = build_event_stream(
        adapter=adapter,
        messages=state.messages_for_adapter,
        provider=provider,
        model=model,
        tools=tools,
        tool_catalog=tool_catalog,
        working_dir=working_dir,
        permission_config=permission_config,
        max_turns=max_turns,
        project_id=project_id,
        session_id=session_id,
        agent_slug=state.agent_slug,
    )

    # Mapping of tool_use_id → original tool metadata, shared across all events in the loop
    tool_use_metadata: dict[str, dict[str, Any]] = {}

    terminal_error_message: str | None = None
    exhausted = False

    try:
        async for event, _session_id in event_stream:
            (
                state.event_turn,
                tools_delta,
                error_message,
                state.turn,
                state.awaiting_tool_results,
            ) = await process_tool_event(
                event, state.event_turn, state.turn, state.awaiting_tool_results, session_id, db, state.content_parts,
                state.thinking_parts, tracker, model_used=model, agent_id=state.agent_slug,
                tool_use_id_to_name=tool_use_metadata,
                tool_result_summaries=state.tool_result_summaries,
            )
            state.tool_calls_count += tools_delta
            if getattr(event, "type", None) == "result":
                state.terminal_finish_reason = getattr(event, "finish_reason", None) or "end_turn"
            elif getattr(event, "type", None) == "tool_result":
                tool_name, tool_input = _extract_tool_metadata(
                    tool_use_metadata,
                    getattr(event, "tool_use_id", None),
                )
                if _is_detached_agent_hub_rebuild_handoff(
                    project_id=project_id,
                    tool_name=tool_name,
                    tool_input=tool_input,
                    tool_content=str(getattr(event, "content", "") or ""),
                ):
                    state.content_parts = [
                        _build_detached_agent_hub_rebuild_closeout(
                            agent_slug=state.agent_slug,
                            external_id=state.external_id,
                            tool_content=str(getattr(event, "content", "") or ""),
                        )
                    ]
                    state.terminal_finish_reason = "end_turn"
                    break

            if error_message and terminal_error_message is None:
                # Record the terminal error, but keep draining the provider stream so
                # SDK-backed generators can unwind cleanly on their own task boundary.
                terminal_error_message = error_message
                await update_session_health(
                    db,
                    session_id,
                    health_detail_for_error(error_message),
                    commit=True,
                )
            elif getattr(event, "type", None) == "tool_result":
                await update_session_health(db, session_id, "calling_model", commit=True)
        else:
            exhausted = True
    finally:
        # Only force-close provider streams when the loop exits early. Redundant
        # close after natural exhaustion can re-enter provider cleanup on a
        # foreign task and inject cancellation into the caller.
        if hasattr(event_stream, "aclose") and not exhausted:
            await event_stream.aclose()

    if terminal_error_message:
        return build_error_result(
            Exception(terminal_error_message), model, provider, session_id, loaded_memory_uuids,
            turns=state.turn, tool_calls_count=state.tool_calls_count,
        )

    return None
