"""Shared execution observability metadata for completion runs."""

from __future__ import annotations

import json
import math
from typing import Any, Literal

from app.models.session import SessionEventType
from app.services.event_storage import store_event

from .turn_budget import resolve_tool_max_turns

ExecutionPath = Literal["single_turn", "multi_turn", "tool_loop"]


def build_execution_observability(
    *,
    session: Any,
    provider: str,
    requested_max_turns: int,
    orchestration_path: ExecutionPath,
    final_finish_reason: str | None,
    execution_status: str | None,
    execution_error: str | None,
    turns_completed: int | None,
    tool_calls_count: int,
    error_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build structured execution metadata for DB/session-event observability."""
    effective_turn_budget = _effective_turn_budget(
        orchestration_path=orchestration_path,
        provider=provider,
        requested_max_turns=requested_max_turns,
    )
    execution = {
        "orchestration_path": orchestration_path,
        "requested_max_turns": requested_max_turns,
        "effective_turn_budget": effective_turn_budget,
        "terminal_stop_reason": _terminal_stop_reason(
            final_finish_reason=final_finish_reason,
            execution_status=execution_status,
            execution_error=execution_error,
            orchestration_path=orchestration_path,
            tool_calls_count=tool_calls_count,
        ),
        "final_finish_reason": final_finish_reason,
        "execution_status": execution_status or "success",
        "execution_error": execution_error,
        "turns_completed": turns_completed,
        "tool_calls_count": tool_calls_count,
        "agent_slug": getattr(session, "agent_slug", None),
        "client_id": getattr(session, "client_id", None),
        "request_source": getattr(session, "request_source", None),
    }
    if error_summary:
        execution["error_summary"] = error_summary
    return execution


async def persist_execution_observability(
    db: Any,
    session: Any,
    session_id: str,
    *,
    provider: str,
    model_used: str,
    requested_max_turns: int,
    orchestration_path: ExecutionPath,
    final_finish_reason: str | None,
    execution_status: str | None,
    execution_error: str | None,
    turns_completed: int | None,
    tool_calls_count: int,
    error_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist execution metadata to the session row and a tool_audit event."""
    execution = build_execution_observability(
        session=session,
        provider=provider,
        requested_max_turns=requested_max_turns,
        orchestration_path=orchestration_path,
        final_finish_reason=final_finish_reason,
        execution_status=execution_status,
        execution_error=execution_error,
        turns_completed=turns_completed,
        tool_calls_count=tool_calls_count,
        error_summary=error_summary,
    )
    metadata = dict(session.provider_metadata or {})
    metadata["execution"] = execution
    session.provider_metadata = metadata
    await store_event(
        db=db,
        session_id=session_id,
        event_type=SessionEventType.TOOL_AUDIT,
        tool_name="execution_observability",
        content=json.dumps(execution, sort_keys=True),
        tool_output=execution,
        model_used=model_used,
        agent_id=getattr(session, "agent_slug", None),
        agent_name=getattr(session, "agent_slug", None),
    )
    return execution


def _effective_turn_budget(
    *,
    orchestration_path: ExecutionPath,
    provider: str,
    requested_max_turns: int,
) -> int:
    if orchestration_path == "tool_loop":
        return resolve_tool_max_turns(provider, requested_max_turns)
    if orchestration_path == "multi_turn":
        if requested_max_turns <= 4:
            return requested_max_turns
        return requested_max_turns + math.ceil(requested_max_turns * 0.1)
    return requested_max_turns


def _terminal_stop_reason(
    *,
    final_finish_reason: str | None,
    execution_status: str | None,
    execution_error: str | None,
    orchestration_path: ExecutionPath,
    tool_calls_count: int,
) -> str:
    if execution_status == "error":
        return execution_error or "error"
    if execution_status == "max_turns" or final_finish_reason == "max_turns":
        return "max_turns"
    if final_finish_reason:
        return final_finish_reason
    if orchestration_path == "tool_loop" and tool_calls_count > 0:
        return "tool_loop_complete"
    return execution_status or "completed"
