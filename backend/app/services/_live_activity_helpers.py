"""Internal helpers for live activity context management and utilities."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from app.models import Session
from app.services.session_scope import extract_tool_scope_paths

_TOUCHED_FILES_LIMIT = 10
_RECENT_PATHS_LIMIT = 20
_VALIDATION_COMMAND_TOKENS = ("dt ", "pytest", "ruff", "tsc", "biome", "sqlfluff", "squawk")
_HEARTBEAT_ACTIVE_PHASES = {
    "injecting_memory",
    "planning",
    "running_tool",
    "reading_file",
    "writing_file",
    "running_validation",
}
_HEARTBEAT_PASSIVE_PHASES = {
    "created",
    "waiting_for_model",
    "finalizing",
    "completed",
    "failed",
    "error",
}

LiveActivity = dict[str, object]


def get_live_activity_ctx(session: Session) -> tuple[LiveActivity, LiveActivity]:
    """Return (metadata_copy, live_activity_copy) from session.provider_metadata."""
    raw_metadata = getattr(session, "provider_metadata", None)
    metadata: LiveActivity = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
    raw = metadata.get("live_activity")
    live: LiveActivity = dict(cast(LiveActivity, raw)) if isinstance(raw, dict) else {}
    return metadata, live


def persist_live_activity(
    session: Session,
    metadata: LiveActivity,
    live_activity: LiveActivity,
) -> None:
    metadata["live_activity"] = live_activity
    session.provider_metadata = metadata


def activity_age_seconds(value: object) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        last_dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if last_dt.tzinfo is None:
        last_dt = last_dt.replace(tzinfo=UTC)
    return max(int((datetime.now(UTC) - last_dt).total_seconds()), 0)


def dedup_append_capped(lst: list[str], items: list[str], limit: int) -> list[str]:
    for item in items:
        if item in lst:
            lst = [x for x in lst if x != item]
        lst.append(item)
    return lst[-limit:]


def append_touched_file(live_activity: LiveActivity, path: str | None) -> None:
    if not path:
        return
    touched = live_activity.get("files_touched")
    live_activity["files_touched"] = dedup_append_capped(
        touched if isinstance(touched, list) else [], [path], _TOUCHED_FILES_LIMIT
    )


def append_recent_paths(
    live_activity: LiveActivity,
    key: str,
    paths: list[str] | None,
) -> None:
    recent = live_activity.get(key)
    live_activity[key] = dedup_append_capped(
        recent if isinstance(recent, list) else [], paths or [], _RECENT_PATHS_LIMIT
    )


def apply_heartbeat_fields(
    live_activity: LiveActivity,
    heartbeat_at: str,
    phase: str | None,
    status: str | None,
    summary: str | None,
    current_tool_name: str | None,
    current_command: str | None,
    last_event_type: str | None,
) -> None:
    """Apply scalar heartbeat fields to live_activity dict."""
    resolved_phase = phase or str(live_activity.get("phase") or "waiting_for_model")
    live_activity["last_heartbeat_at"] = heartbeat_at
    live_activity["last_event_at"] = heartbeat_at
    live_activity["termination_reason"] = None
    live_activity["status"] = status or str(live_activity.get("status") or "active")
    live_activity["phase"] = resolved_phase
    if summary is not None:
        live_activity["summary"] = summary
    if current_tool_name is not None:
        live_activity["current_tool_name"] = current_tool_name
        live_activity["last_tool_name"] = current_tool_name
    elif resolved_phase in _HEARTBEAT_PASSIVE_PHASES:
        live_activity["current_tool_name"] = None
    if current_command is not None:
        live_activity["current_command"] = current_command
        live_activity["last_command"] = current_command
    if last_event_type is not None:
        live_activity["last_event_type"] = last_event_type
    if (
        current_tool_name
        or resolved_phase in _HEARTBEAT_ACTIVE_PHASES
        or (last_event_type and last_event_type != "heartbeat")
        or not live_activity.get("last_model_activity_at")
    ):
        live_activity["last_model_activity_at"] = heartbeat_at
    if resolved_phase in _HEARTBEAT_PASSIVE_PHASES and not current_tool_name:
        live_activity["outstanding_tool_calls"] = 0


def apply_heartbeat_path_updates(
    live_activity: LiveActivity,
    active_read_paths: list[str] | None,
    active_write_paths: list[str] | None,
) -> None:
    """Apply read/write path updates from a heartbeat to live_activity."""
    if active_read_paths:
        live_activity["last_read_path"] = active_read_paths[-1]
        append_recent_paths(live_activity, "recent_read_paths", active_read_paths)
    if active_write_paths:
        live_activity["last_write_path"] = active_write_paths[-1]
        append_recent_paths(live_activity, "recent_write_paths", active_write_paths)
        for path in active_write_paths:
            append_touched_file(live_activity, path)


def build_response_base(session: Session, raw: LiveActivity) -> tuple[LiveActivity, str, str, int | None]:
    """Build the base response dict with phase, status, and quiet_for_seconds from raw live activity."""
    response = dict(raw)
    phase = str(response.get("phase") or "created")
    status = str(response.get("status") or ("active" if session.status == "active" else session.status))
    response["phase"] = phase
    response["status"] = status
    quiet_for_seconds = activity_age_seconds(
        response.get("last_model_activity_at") or response.get("last_event_at"),
    )
    response["quiet_for_seconds"] = quiet_for_seconds
    return response, phase, status, quiet_for_seconds


def build_fallback_raw(session: Session) -> LiveActivity | None:
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


def tool_phase(
    tool_name: str | None,
    tool_input: LiveActivity | None,
    *,
    base_path: str | None = None,
) -> tuple[str, str, str | None, str | None]:
    """Return (phase, summary, path, command) for a tool_use event."""
    normalized = (tool_name or "").lower()
    command: str | None = None
    path: str | None = None
    observed_reads: list[str] = []
    observed_writes: list[str] = []
    if isinstance(tool_input, dict):
        cmd_val = tool_input.get("command") or tool_input.get("cmd")
        command = cmd_val if isinstance(cmd_val, str) and cmd_val else None
        for key in ("file_path", "path", "target_file"):
            val = tool_input.get(key)
            if isinstance(val, str) and val:
                path = val
                break
        base_path = next(
            (
                value
                for key in ("workdir", "cwd")
                if isinstance((value := tool_input.get(key)), str) and value
            ),
            base_path,
        )
        observed_reads, observed_writes = extract_tool_scope_paths(
            tool_name,
            dict(tool_input),
            base_path=base_path,
        )
        if not path:
            path = (observed_writes or observed_reads or [None])[0]

    if "read" in normalized:
        return "reading_file", f"Reading {path or 'file'}", path, command
    if "write" in normalized or "edit" in normalized:
        return "writing_file", f"Writing {path or 'file'}", path, command
    if observed_writes:
        return "writing_file", f"Writing {path or 'file'}", path, command
    if observed_reads:
        return "reading_file", f"Reading {path or 'file'}", path, command
    if command:
        if any(token in command for token in _VALIDATION_COMMAND_TOKENS):
            return "running_validation", f"Running validation: {command[:100]}", path, command
        return "running_tool", f"Running command: {command[:100]}", path, command
    return "running_tool", f"Running tool: {tool_name or 'unknown'}", path, command
