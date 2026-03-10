"""Structured live execution activity for session observability."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.models import Session

_ACTIVE_PHASES = {
    "created",
    "injecting_memory",
    "waiting_for_model",
    "planning",
    "running_tool",
    "reading_file",
    "writing_file",
    "running_validation",
    "finalizing",
}
_QUIET_AFTER_SECONDS = 60
_STALL_AFTER_SECONDS = 180
_POST_TOOL_STALL_AFTER_SECONDS = 120
_TOUCHED_FILES_LIMIT = 10
_RECENT_PATHS_LIMIT = 20


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _metadata_dict(session: Session) -> dict[str, Any]:
    raw_metadata = getattr(session, "provider_metadata", None)
    metadata = raw_metadata if isinstance(raw_metadata, dict) else None
    if metadata is None:
        metadata = {}
    return dict(metadata)


def _live_activity(metadata: dict[str, Any]) -> dict[str, Any]:
    live_activity = metadata.get("live_activity")
    if isinstance(live_activity, dict):
        return dict(live_activity)
    return {}


def _path_from_tool_input(tool_input: dict[str, Any] | None) -> str | None:
    if not isinstance(tool_input, dict):
        return None
    for key in ("file_path", "path", "target_file"):
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _command_from_tool_input(tool_input: dict[str, Any] | None) -> str | None:
    if not isinstance(tool_input, dict):
        return None
    value = tool_input.get("command")
    return value if isinstance(value, str) and value else None


def _tool_phase(tool_name: str | None, tool_input: dict[str, Any] | None) -> tuple[str, str]:
    normalized = (tool_name or "").lower()
    command = _command_from_tool_input(tool_input)

    if "read" in normalized:
        path = _path_from_tool_input(tool_input)
        return "reading_file", f"Reading {path or 'file'}"

    if "write" in normalized or "edit" in normalized:
        path = _path_from_tool_input(tool_input)
        return "writing_file", f"Writing {path or 'file'}"

    if command:
        validation_tokens = ("dt ", "pytest", "ruff", "tsc", "biome", "sqlfluff", "squawk")
        if any(token in command for token in validation_tokens):
            return "running_validation", f"Running validation: {command[:100]}"
        return "running_tool", f"Running command: {command[:100]}"

    return "running_tool", f"Running tool: {tool_name or 'unknown'}"


def _append_touched_file(live_activity: dict[str, Any], path: str | None) -> None:
    if not path:
        return
    touched = live_activity.get("files_touched")
    if not isinstance(touched, list):
        touched = []
    if path in touched:
        touched = [p for p in touched if p != path]
    touched.append(path)
    live_activity["files_touched"] = touched[-_TOUCHED_FILES_LIMIT:]


def _append_recent_paths(
    live_activity: dict[str, Any],
    key: str,
    paths: list[str] | None,
) -> None:
    recent = live_activity.get(key)
    if not isinstance(recent, list):
        recent = []
    for path in paths or []:
        if path in recent:
            recent = [existing for existing in recent if existing != path]
        recent.append(path)
    live_activity[key] = recent[-_RECENT_PATHS_LIMIT:]


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
    metadata = _metadata_dict(session)
    live_activity = _live_activity(metadata)
    now_iso = _now_iso()

    live_activity["last_event_type"] = event_type
    live_activity["last_event_at"] = now_iso
    if model_used:
        live_activity["model_used"] = model_used

    if event_type == "memory_inject":
        _mark_non_terminal_state(
            live_activity,
            phase="injecting_memory",
            summary="Injecting memory context",
            now_iso=now_iso,
        )
    elif event_type == "thinking":
        _mark_non_terminal_state(
            live_activity,
            phase="planning",
            summary="Model planning",
            now_iso=now_iso,
        )
    elif event_type == "tool_use":
        phase, summary = _tool_phase(tool_name, tool_input)
        _mark_non_terminal_state(live_activity, phase=phase, summary=summary, now_iso=now_iso)
        live_activity["current_tool_name"] = tool_name
        live_activity["last_tool_name"] = tool_name
        live_activity["last_tool_started_at"] = now_iso
        live_activity["outstanding_tool_calls"] = max(
            int(live_activity.get("outstanding_tool_calls") or 0) + 1,
            1,
        )
        live_activity["tool_calls_count"] = int(live_activity.get("tool_calls_count") or 0) + 1
        path = _path_from_tool_input(tool_input)
        command = _command_from_tool_input(tool_input)
        if phase == "reading_file":
            live_activity["last_read_path"] = path
        elif phase == "writing_file":
            live_activity["last_write_path"] = path
            _append_touched_file(live_activity, path)
        if command:
            live_activity["last_command"] = command
            if phase == "running_validation":
                live_activity["last_validation_command"] = command
    elif event_type == "tool_result":
        is_error = bool(tool_output.get("is_error")) if isinstance(tool_output, dict) else False
        live_activity["phase"] = "waiting_for_model"
        live_activity["status"] = "active"
        live_activity["summary"] = (
            f"Tool failed: {tool_name or live_activity.get('last_tool_name') or 'unknown'}"
            if is_error
            else f"Waiting for model after {tool_name or live_activity.get('last_tool_name') or 'tool'}"
        )
        live_activity["current_tool_name"] = None
        live_activity["last_tool_name"] = tool_name or live_activity.get("last_tool_name")
        live_activity["last_tool_finished_at"] = now_iso
        live_activity["last_tool_error"] = is_error
        live_activity["outstanding_tool_calls"] = max(
            int(live_activity.get("outstanding_tool_calls") or 0) - 1,
            0,
        )
        live_activity["stall_reason"] = None
        live_activity["termination_reason"] = None
        if isinstance(tool_output, dict):
            exit_code = tool_output.get("exit_code")
            if isinstance(exit_code, int):
                live_activity["last_command_exit_code"] = exit_code
    elif event_type == "assistant_message":
        summary = "Finalizing response"
        if isinstance(content, str) and content.strip():
            summary = f"Assistant responded: {content.strip()[:100]}"
        _mark_non_terminal_state(live_activity, phase="finalizing", summary=summary, now_iso=now_iso)
        live_activity["current_tool_name"] = None
        live_activity["outstanding_tool_calls"] = 0
    elif event_type == "error":
        live_activity["phase"] = "error"
        live_activity["status"] = "error"
        live_activity["summary"] = f"Execution error: {(content or 'unknown error')[:120]}"
        live_activity["termination_reason"] = content
        live_activity["current_tool_name"] = None
        live_activity["outstanding_tool_calls"] = 0
        live_activity["last_model_activity_at"] = now_iso

    metadata["live_activity"] = live_activity
    session.provider_metadata = metadata


def mark_session_execution_start(session: Session, summary: str = "Waiting for model response") -> None:
    """Mark a session as actively executing before the provider responds."""
    metadata = _metadata_dict(session)
    live_activity = _live_activity(metadata)
    now_iso = _now_iso()
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
    metadata["live_activity"] = live_activity
    session.provider_metadata = metadata


def mark_session_terminal_state(
    session: Session,
    *,
    phase: str,
    status: str,
    summary: str,
    termination_reason: str | None,
) -> None:
    """Persist terminal execution state on the session metadata."""
    metadata = _metadata_dict(session)
    live_activity = _live_activity(metadata)
    now_iso = _now_iso()
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
    metadata["live_activity"] = live_activity
    session.provider_metadata = metadata


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
    metadata = _metadata_dict(session)
    live_activity = _live_activity(metadata)

    live_activity["last_heartbeat_at"] = heartbeat_at
    live_activity["last_event_at"] = heartbeat_at
    live_activity["last_model_activity_at"] = heartbeat_at
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

    metadata["live_activity"] = live_activity
    session.provider_metadata = metadata


def build_live_activity_response(session: Session) -> dict[str, Any] | None:
    """Build API-ready live activity payload with dynamic quiet/stall classification."""
    metadata = _metadata_dict(session)
    raw = _live_activity(metadata)
    if not raw:
        return None

    response = dict(raw)
    phase = str(response.get("phase") or "created")
    status = str(response.get("status") or ("active" if session.status == "active" else session.status))
    response["phase"] = phase
    response["status"] = status

    last_activity = response.get("last_model_activity_at") or response.get("last_event_at")
    quiet_for_seconds: int | None = None
    if isinstance(last_activity, str):
        try:
            last_dt = datetime.fromisoformat(last_activity.replace("Z", "+00:00"))
            quiet_for_seconds = max(int((datetime.now(UTC) - last_dt).total_seconds()), 0)
        except ValueError:
            quiet_for_seconds = None

    response["quiet_for_seconds"] = quiet_for_seconds
    health = "idle"
    stalled = False
    stall_reason = None

    if session.status == "active" and phase in _ACTIVE_PHASES:
        health = "active"
        post_tool_wait = (
            phase == "waiting_for_model"
            and response.get("last_event_type") == "tool_result"
            and int(response.get("outstanding_tool_calls") or 0) == 0
        )
        stall_after_seconds = (
            _POST_TOOL_STALL_AFTER_SECONDS if post_tool_wait else _STALL_AFTER_SECONDS
        )
        if quiet_for_seconds is not None and quiet_for_seconds >= stall_after_seconds:
            health = "stalled"
            stalled = True
            stall_reason = (
                f"No model activity for {quiet_for_seconds}s after tool_result"
                if post_tool_wait
                else f"No model activity for {quiet_for_seconds}s while phase={phase}"
            )
        elif quiet_for_seconds is not None and quiet_for_seconds >= _QUIET_AFTER_SECONDS:
            health = "quiet"
    elif status == "error":
        health = "error"
    elif session.status == "completed":
        health = "completed"
    elif session.status == "failed":
        health = "failed"

    response["health"] = health
    response["stalled"] = stalled
    response["stall_reason"] = stall_reason or response.get("stall_reason")
    response["files_touched"] = response.get("files_touched") or []
    response["last_heartbeat_at"] = response.get("last_heartbeat_at")
    return response
