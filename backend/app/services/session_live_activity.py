"""Structured live execution activity for session observability."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.models import Session
from app.services._session_lifecycle import (
    _NON_ACTIONABLE_LIFECYCLE_STATES,
    _apply_lifecycle_state,
    _apply_terminal_overrides,
    _classify_active_health,
)

_TOUCHED_FILES_LIMIT = 10
_RECENT_PATHS_LIMIT = 20
_VALIDATION_COMMAND_TOKENS = ("dt ", "pytest", "ruff", "tsc", "biome", "sqlfluff", "squawk")


def _get_live_activity_ctx(session: Session) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (metadata_copy, live_activity_copy) from session.provider_metadata."""
    raw_metadata = getattr(session, "provider_metadata", None)
    metadata: dict[str, Any] = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
    raw = metadata.get("live_activity")
    live: dict[str, Any] = dict(raw) if isinstance(raw, dict) else {}
    return metadata, live


def _activity_age_seconds(value: Any) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        last_dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=UTC)
    return max(int((datetime.now(UTC) - last_dt).total_seconds()), 0)


def _tool_phase(
    tool_name: str | None,
    tool_input: dict[str, Any] | None,
) -> tuple[str, str, str | None, str | None]:
    """Return (phase, summary, path, command) for a tool_use event."""
    normalized = (tool_name or "").lower()
    command: str | None = None
    path: str | None = None
    if isinstance(tool_input, dict):
        cmd_val = tool_input.get("command")
        command = cmd_val if isinstance(cmd_val, str) and cmd_val else None
        for key in ("file_path", "path", "target_file"):
            val = tool_input.get(key)
            if isinstance(val, str) and val:
                path = val
                break

    if "read" in normalized:
        return "reading_file", f"Reading {path or 'file'}", path, command
    if "write" in normalized or "edit" in normalized:
        return "writing_file", f"Writing {path or 'file'}", path, command
    if command:
        if any(token in command for token in _VALIDATION_COMMAND_TOKENS):
            return "running_validation", f"Running validation: {command[:100]}", path, command
        return "running_tool", f"Running command: {command[:100]}", path, command
    return "running_tool", f"Running tool: {tool_name or 'unknown'}", path, command


def _dedup_append_capped(lst: list[str], items: list[str], limit: int) -> list[str]:
    for item in items:
        if item in lst:
            lst = [x for x in lst if x != item]
        lst.append(item)
    return lst[-limit:]


def _append_touched_file(live_activity: dict[str, Any], path: str | None) -> None:
    if not path:
        return
    touched = live_activity.get("files_touched")
    live_activity["files_touched"] = _dedup_append_capped(
        touched if isinstance(touched, list) else [], [path], _TOUCHED_FILES_LIMIT
    )


def _append_recent_paths(
    live_activity: dict[str, Any],
    key: str,
    paths: list[str] | None,
) -> None:
    recent = live_activity.get(key)
    live_activity[key] = _dedup_append_capped(
        recent if isinstance(recent, list) else [], paths or [], _RECENT_PATHS_LIMIT
    )


def _mark_non_terminal_state(
    live_activity: dict[str, Any],
    *,
    phase: str,
    summary: str,
    now_iso: str,
) -> None:
    live_activity["phase"] = phase
    live_activity["status"] = "active"
    live_activity["summary"] = summary
    live_activity["termination_reason"] = None
    live_activity["stall_reason"] = None
    live_activity["last_model_activity_at"] = now_iso


def _handle_tool_use_event(
    live_activity: dict[str, Any],
    tool_name: str | None,
    tool_input: dict[str, Any] | None,
    now_iso: str,
) -> None:
    phase, summary, path, command = _tool_phase(tool_name, tool_input)
    _mark_non_terminal_state(live_activity, phase=phase, summary=summary, now_iso=now_iso)
    live_activity["current_tool_name"] = tool_name
    live_activity["last_tool_name"] = tool_name
    live_activity["last_tool_started_at"] = now_iso
    live_activity["outstanding_tool_calls"] = max(
        int(live_activity.get("outstanding_tool_calls") or 0) + 1, 1,
    )
    live_activity["tool_calls_count"] = int(live_activity.get("tool_calls_count") or 0) + 1
    if phase == "reading_file":
        live_activity["last_read_path"] = path
    elif phase == "writing_file":
        live_activity["last_write_path"] = path
        _append_touched_file(live_activity, path)
    if command:
        live_activity["last_command"] = command
        if phase == "running_validation":
            live_activity["last_validation_command"] = command


def _handle_tool_result_event(
    live_activity: dict[str, Any],
    tool_name: str | None,
    tool_output: dict[str, Any] | None,
    now_iso: str,
) -> None:
    is_error = bool(tool_output.get("is_error")) if isinstance(tool_output, dict) else False
    resolved_tool = tool_name or live_activity.get("last_tool_name") or "unknown"
    live_activity["phase"] = "waiting_for_model"
    live_activity["status"] = "active"
    live_activity["summary"] = (
        f"Tool failed: {resolved_tool}" if is_error
        else f"Waiting for model after {resolved_tool}"
    )
    live_activity["current_tool_name"] = None
    live_activity["last_tool_name"] = tool_name or live_activity.get("last_tool_name")
    live_activity["last_tool_finished_at"] = now_iso
    live_activity["last_tool_error"] = is_error
    live_activity["outstanding_tool_calls"] = max(
        int(live_activity.get("outstanding_tool_calls") or 0) - 1, 0,
    )
    live_activity["stall_reason"] = None
    live_activity["termination_reason"] = None
    if isinstance(tool_output, dict):
        exit_code = tool_output.get("exit_code")
        if isinstance(exit_code, int):
            live_activity["last_command_exit_code"] = exit_code


def _handle_assistant_message_event(
    live_activity: dict[str, Any],
    content: str | None,
    now_iso: str,
) -> None:
    summary = (
        f"Assistant responded: {content.strip()[:100]}"
        if isinstance(content, str) and content.strip()
        else "Finalizing response"
    )
    _mark_non_terminal_state(live_activity, phase="finalizing", summary=summary, now_iso=now_iso)
    live_activity["current_tool_name"] = None
    live_activity["outstanding_tool_calls"] = 0


def _handle_error_event(
    live_activity: dict[str, Any],
    content: str | None,
    now_iso: str,
) -> None:
    live_activity["phase"] = "error"
    live_activity["status"] = "error"
    live_activity["summary"] = f"Execution error: {(content or 'unknown error')[:120]}"
    live_activity["termination_reason"] = content
    live_activity["current_tool_name"] = None
    live_activity["outstanding_tool_calls"] = 0
    live_activity["last_model_activity_at"] = now_iso


def _persist_live_activity(
    session: Session,
    metadata: dict[str, Any],
    live_activity: dict[str, Any],
) -> None:
    metadata["live_activity"] = live_activity
    session.provider_metadata = metadata


def update_live_activity_for_event(
    session: Session,
    *,
    event_type: str,
    tool_name: str | None = None,
    tool_input: dict[str, Any] | None = None,
    tool_output: dict[str, Any] | None = None,
    content: str | None = None,
    model_used: str | None = None,
) -> None:
    """Update provider_metadata.live_activity from a stored session event."""
    metadata, live_activity = _get_live_activity_ctx(session)
    now_iso = datetime.now(UTC).isoformat()

    live_activity["last_event_type"] = event_type
    live_activity["last_event_at"] = now_iso
    if model_used:
        live_activity["model_used"] = model_used

    if event_type == "memory_inject":
        _mark_non_terminal_state(
            live_activity, phase="injecting_memory", summary="Injecting memory context", now_iso=now_iso
        )
    elif event_type == "thinking":
        _mark_non_terminal_state(live_activity, phase="planning", summary="Model planning", now_iso=now_iso)
    elif event_type == "tool_use":
        _handle_tool_use_event(live_activity, tool_name, tool_input, now_iso)
    elif event_type == "tool_result":
        _handle_tool_result_event(live_activity, tool_name, tool_output, now_iso)
    elif event_type == "assistant_message":
        _handle_assistant_message_event(live_activity, content, now_iso)
    elif event_type == "error":
        _handle_error_event(live_activity, content, now_iso)

    _persist_live_activity(session, metadata, live_activity)


def mark_session_execution_start(session: Session, summary: str = "Waiting for model response") -> None:
    """Mark a session as actively executing before the provider responds."""
    metadata, live_activity = _get_live_activity_ctx(session)
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
    _persist_live_activity(session, metadata, live_activity)


def mark_session_terminal_state(
    session: Session,
    *,
    phase: str,
    status: str,
    summary: str,
    termination_reason: str | None,
) -> None:
    """Persist terminal execution state on the session metadata."""
    metadata, live_activity = _get_live_activity_ctx(session)
    now_iso = datetime.now(UTC).isoformat()
    live_activity.update(
        {
            "phase": phase,
            "status": status,
            "summary": summary,
            "termination_reason": termination_reason,
            "stall_reason": None,
            "current_tool_name": None,
            "outstanding_tool_calls": 0,
            "last_event_at": now_iso,
            "last_model_activity_at": now_iso,
        }
    )
    _persist_live_activity(session, metadata, live_activity)


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
    metadata, live_activity = _get_live_activity_ctx(session)

    live_activity["last_heartbeat_at"] = heartbeat_at
    live_activity["last_event_at"] = heartbeat_at
    live_activity["last_model_activity_at"] = heartbeat_at
    live_activity["termination_reason"] = None
    live_activity["status"] = status or str(live_activity.get("status") or "active")
    live_activity["phase"] = phase or str(live_activity.get("phase") or "waiting_for_model")
    if summary is not None:
        live_activity["summary"] = summary
    if current_tool_name is not None:
        live_activity["current_tool_name"] = current_tool_name
        live_activity["last_tool_name"] = current_tool_name
    if current_command is not None:
        live_activity["current_command"] = current_command
        live_activity["last_command"] = current_command
    if last_event_type is not None:
        live_activity["last_event_type"] = last_event_type
    if active_read_paths:
        live_activity["last_read_path"] = active_read_paths[-1]
        _append_recent_paths(live_activity, "recent_read_paths", active_read_paths)
    if active_write_paths:
        live_activity["last_write_path"] = active_write_paths[-1]
        _append_recent_paths(live_activity, "recent_write_paths", active_write_paths)
        for path in active_write_paths:
            _append_touched_file(live_activity, path)

    _persist_live_activity(session, metadata, live_activity)


def _build_fallback_raw(session: Session) -> dict[str, Any] | None:
    """Return a fallback raw live_activity dict for active sessions with no recorded data."""
    if session.status != "active":
        return None
    last_updated = session.updated_at or getattr(session, "last_activity_at", None) or session.created_at
    last_updated_iso = last_updated.isoformat() if last_updated is not None else None
    return {
        "phase": "unknown",
        "status": "active",
        "summary": "No structured activity recorded",
        "last_event_type": None,
        "last_event_at": last_updated_iso,
        "last_model_activity_at": last_updated_iso,
        "outstanding_tool_calls": 0,
        "tool_calls_count": 0,
        "files_touched": [],
        "last_heartbeat_at": None,
    }


def build_live_activity_response(
    session: Session,
    *,
    has_owner_lane: bool = False,
    has_specialist_lane: bool = False,
) -> dict[str, Any] | None:
    """Build API-ready live activity payload with dynamic quiet/stall classification."""
    _, raw = _get_live_activity_ctx(session)
    if not raw:
        raw = _build_fallback_raw(session)
        if raw is None:
            return None

    response = dict(raw)
    phase = str(response.get("phase") or "created")
    status = str(response.get("status") or ("active" if session.status == "active" else session.status))
    response["phase"] = phase
    response["status"] = status
    quiet_for_seconds = _activity_age_seconds(
        response.get("last_model_activity_at") or response.get("last_event_at"),
    )
    response["quiet_for_seconds"] = quiet_for_seconds

    if session.status == "active":
        health, stalled, stall_reason = _classify_active_health(response, phase, quiet_for_seconds)
    elif status == "error":
        health, stalled, stall_reason = "error", False, None
    else:
        health, stalled, stall_reason = _apply_terminal_overrides(response, session, phase, status), False, None
    response["health"] = health
    response["stalled"] = stalled
    response["stall_reason"] = stall_reason or response.get("stall_reason")
    response["files_touched"] = response.get("files_touched") or []
    response["last_heartbeat_at"] = response.get("last_heartbeat_at")
    last_heartbeat_age = _activity_age_seconds(response.get("last_heartbeat_at"))
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
