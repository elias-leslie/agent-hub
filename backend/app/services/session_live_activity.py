"""Structured live execution activity for session observability."""

from __future__ import annotations

from datetime import UTC, datetime

from app.models import Session
from app.services._live_activity_event_handlers import (
    handle_assistant_message_event,
    handle_error_event,
    handle_tool_result_event,
    handle_tool_use_event,
    mark_non_terminal_state,
)
from app.services._live_activity_helpers import (
    LiveActivity,
    activity_age_seconds,
    apply_heartbeat_fields,
    apply_heartbeat_path_updates,
    build_fallback_raw,
    build_response_base,
    get_live_activity_ctx,
    persist_live_activity,
)
from app.services._session_lifecycle import (
    _NON_ACTIONABLE_LIFECYCLE_STATES,
    _apply_lifecycle_state,
    _apply_terminal_overrides,
    _classify_active_health,
)
from app.services.session_scope import resolve_scope_base_path


def update_live_activity_for_event(
    session: Session,
    *,
    event_type: str,
    tool_name: str | None = None,
    tool_input: LiveActivity | None = None,
    tool_output: LiveActivity | None = None,
    content: str | None = None,
    model_used: str | None = None,
) -> None:
    """Update provider_metadata.live_activity from a stored session event."""
    metadata, live_activity = get_live_activity_ctx(session)
    now_iso = datetime.now(UTC).isoformat()

    live_activity["last_event_type"] = event_type
    live_activity["last_event_at"] = now_iso
    if model_used:
        live_activity["model_used"] = model_used

    if event_type == "memory_inject":
        mark_non_terminal_state(
            live_activity, phase="injecting_memory", summary="Injecting memory context", now_iso=now_iso
        )
    elif event_type == "thinking":
        mark_non_terminal_state(live_activity, phase="planning", summary="Model planning", now_iso=now_iso)
    elif event_type == "tool_use":
        handle_tool_use_event(
            live_activity,
            tool_name,
            tool_input,
            now_iso,
            base_path=resolve_scope_base_path(metadata, None),
        )
    elif event_type == "tool_result":
        handle_tool_result_event(live_activity, tool_name, tool_output, now_iso)
    elif event_type == "assistant_message":
        handle_assistant_message_event(live_activity, content, now_iso)
    elif event_type == "error":
        handle_error_event(live_activity, content, now_iso)

    persist_live_activity(session, metadata, live_activity)


def mark_session_execution_start(session: Session, summary: str = "Waiting for model response") -> None:
    """Mark a session as actively executing before the provider responds."""
    metadata, live_activity = get_live_activity_ctx(session)
    now_iso = datetime.now(UTC).isoformat()
    live_activity.update(
        {
            "phase": "waiting_for_model",
            "status": "active",
            "summary": summary,
            "last_event_type": "session_start",
            "last_event_at": now_iso,
            "last_model_activity_at": now_iso,
            "termination_reason": None,
            "stall_reason": None,
            "outstanding_tool_calls": int(live_activity.get("outstanding_tool_calls") or 0),
            "tool_calls_count": int(live_activity.get("tool_calls_count") or 0),
        }
    )
    persist_live_activity(session, metadata, live_activity)


def mark_session_terminal_state(
    session: Session,
    *,
    phase: str,
    status: str,
    summary: str,
    termination_reason: str | None,
) -> None:
    """Persist terminal execution state on the session metadata."""
    metadata, live_activity = get_live_activity_ctx(session)
    now_iso = datetime.now(UTC).isoformat()
    live_activity.update(
        {
            "phase": phase,
            "status": status,
            "summary": summary,
            "termination_reason": termination_reason,
            "stall_reason": None,
            "current_tool_name": None,
            "current_topic": None,
            "outstanding_tool_calls": 0,
            "last_event_at": now_iso,
            "last_model_activity_at": now_iso,
        }
    )
    persist_live_activity(session, metadata, live_activity)


def mark_session_completed(
    session: Session,
    *,
    summary: str,
    termination_reason: str | None,
) -> None:
    """Synchronize completed status with terminal live activity metadata."""
    session.status = "completed"
    session.health_detail = "completed"
    mark_session_terminal_state(
        session,
        phase="completed",
        status="completed",
        summary=summary,
        termination_reason=termination_reason,
    )


def apply_live_activity_heartbeat(
    session: Session,
    *,
    heartbeat_at: str,
    phase: str | None = None,
    status: str | None = None,
    summary: str | None = None,
    current_tool_name: str | None = None,
    current_command: str | None = None,
    last_event_type: str | None = None,
    active_read_paths: list[str] | None = None,
    active_write_paths: list[str] | None = None,
) -> None:
    """Update live activity directly from an external session heartbeat."""
    metadata, live_activity = get_live_activity_ctx(session)
    apply_heartbeat_fields(live_activity, heartbeat_at, phase, status, summary, current_tool_name, current_command, last_event_type)
    apply_heartbeat_path_updates(live_activity, active_read_paths, active_write_paths)
    persist_live_activity(session, metadata, live_activity)


def build_live_activity_response(
    session: Session,
    *,
    has_owner_lane: bool = False,
    has_specialist_lane: bool = False,
) -> LiveActivity | None:
    """Build API-ready live activity payload with dynamic quiet/stall classification."""
    _, raw = get_live_activity_ctx(session)
    source = "runtime"
    if not raw:
        raw = build_fallback_raw(session)
        source = "fallback"
        if raw is None:
            return None

    response, phase, status, quiet_for_seconds = build_response_base(session, raw)

    if session.status == "active":
        health, stalled, stall_reason = _classify_active_health(response, phase, quiet_for_seconds)
    elif status == "error":
        health, stalled, stall_reason = "error", False, None
    else:
        health, stalled, stall_reason = _apply_terminal_overrides(response, session, phase, status), False, None
    response["source"] = source
    response["health"] = health
    response["stalled"] = stalled
    response["stall_reason"] = stall_reason or response.get("stall_reason")
    response["files_touched"] = response.get("files_touched") or []
    response["last_heartbeat_at"] = response.get("last_heartbeat_at")
    last_heartbeat_age = activity_age_seconds(response.get("last_heartbeat_at"))
    _apply_lifecycle_state(
        session, response,
        has_owner_lane=has_owner_lane,
        has_specialist_lane=has_specialist_lane,
        last_heartbeat_age=last_heartbeat_age,
    )
    return response


def is_session_actionably_active(
    session: Session,
    *,
    has_owner_lane: bool = False,
    has_specialist_lane: bool = False,
) -> bool:
    """Return whether a session should count as active work for coordination views."""
    response = build_live_activity_response(
        session,
        has_owner_lane=has_owner_lane,
        has_specialist_lane=has_specialist_lane,
    )
    if not response:
        return False
    lifecycle_state = str(response.get("lifecycle_state") or "idle")
    return lifecycle_state not in _NON_ACTIONABLE_LIFECYCLE_STATES
