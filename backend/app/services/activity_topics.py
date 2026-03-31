"""Shared topic derivation for progress updates and live activity."""

from __future__ import annotations

from typing import Any

from app.services.session_scope import extract_tool_scope_paths

_PATH_KEYS = ("file_path", "path", "target_file")
_COMMAND_KEYS = ("command", "cmd")


def _string_value(value: object) -> str | None:
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


def _topic(prefix: str, value: str | None, *, limit: int = 160) -> str | None:
    text = _string_value(value)
    if not text:
        return None
    combined = f"{prefix}:{text}"
    return combined if len(combined) <= limit else combined[: limit - 1] + "…"


def default_progress_topic(
    *,
    external_id: str | None = None,
    session_id: str | None = None,
    agent_slug: str | None = None,
) -> str | None:
    """Return a stable default topic for one execution lane."""
    if external_id:
        return _topic("task" if external_id.startswith("task-") else "work", external_id)
    if session_id:
        return _topic("session", session_id)
    if agent_slug:
        return _topic("agent", agent_slug)
    return None


def derive_activity_topic(
    tool_name: str | None,
    tool_input: dict[str, Any] | None,
    *,
    fallback: str | None = None,
    base_path: str | None = None,
) -> str | None:
    """Derive a compact topic label from task, file, agent, or command context."""
    payload = dict(tool_input) if isinstance(tool_input, dict) else {}

    task_id = _string_value(payload.get("task_id") or payload.get("external_id"))
    if task_id:
        return _topic("task" if task_id.startswith("task-") else "work", task_id)

    session_id = _string_value(payload.get("session_id"))
    if session_id:
        return _topic("session", session_id)

    agent_slug = _string_value(payload.get("agent_slug"))
    if agent_slug:
        return _topic("agent", agent_slug)

    explicit_path = next(
        (_string_value(payload.get(key)) for key in _PATH_KEYS if _string_value(payload.get(key))),
        None,
    )
    if explicit_path:
        return _topic("file", explicit_path)

    resolved_base = next(
        (
            _string_value(payload.get(key))
            for key in ("workdir", "cwd")
            if _string_value(payload.get(key))
        ),
        base_path,
    )
    observed_reads, observed_writes = extract_tool_scope_paths(
        tool_name,
        payload,
        base_path=resolved_base,
    )
    if observed_writes:
        return _topic("file", observed_writes[0])
    if observed_reads:
        return _topic("file", observed_reads[0])

    command = next(
        (_string_value(payload.get(key)) for key in _COMMAND_KEYS if _string_value(payload.get(key))),
        None,
    )
    if command:
        parts = command.split()
        if parts:
            if parts[0] in {"dt", "st", "db"} and len(parts) > 1:
                return _topic("command", f"{parts[0]} {parts[1]}")
            return _topic("command", parts[0])

    if fallback:
        return fallback
    return _topic("tool", tool_name)


__all__ = [
    "default_progress_topic",
    "derive_activity_topic",
]
