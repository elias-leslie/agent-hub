"""Build compact project-index context from canonical .index.yaml files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .context_profiles import MemoryConsumerProfile, resolve_consumer_profile

_WORKSPACE_BASE = Path("/srv/workspaces/projects")
_RUNTIME_BASE_KEYS: tuple[str, ...] = ("project", "environment", "services", "urls", "network")
_STARTUP_EXTRA_KEYS: tuple[str, ...] = ("pages",)
_PAGE_TASK_TYPES = {"frontend", "ui-design", "design-review", "test", "verification"}


def _read_project_index(project_id: str) -> dict[str, Any] | None:
    index_path = _WORKSPACE_BASE / project_id / ".index.yaml"
    if not index_path.is_file():
        return None
    try:
        data = yaml.safe_load(index_path.read_text())
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _copy_compact_value(key: str, value: Any) -> Any:
    if key == "services" and isinstance(value, dict):
        return {subkey: subvalue for subkey, subvalue in value.items() if subkey != "infrastructure"}
    return value


def _keys_for_profile(
    consumer_profile: str | None,
    task_type: str | None,
) -> tuple[str, ...]:
    profile = resolve_consumer_profile(consumer_profile)
    keys = list(_RUNTIME_BASE_KEYS)
    if profile == MemoryConsumerProfile.AGENT_STARTUP or task_type in _PAGE_TASK_TYPES:
        keys.extend(_STARTUP_EXTRA_KEYS)
    return tuple(keys)


def build_project_index_payload(
    project_id: str | None,
    *,
    consumer_profile: str | None,
    task_type: str | None = None,
) -> dict[str, Any] | None:
    """Return the compact project-index payload for a given consumer."""
    if not project_id:
        return None
    data = _read_project_index(project_id)
    if not data:
        return None

    payload: dict[str, Any] = {}
    for key in _keys_for_profile(consumer_profile, task_type):
        if key not in data:
            continue
        payload[key] = _copy_compact_value(key, data[key])
    return payload or None


def format_project_index_context(
    project_id: str | None,
    *,
    consumer_profile: str | None,
    task_type: str | None = None,
) -> str:
    """Render compact project-index metadata as a standalone context block."""
    payload = build_project_index_payload(
        project_id,
        consumer_profile=consumer_profile,
        task_type=task_type,
    )
    if not payload:
        return ""
    compact_yaml = yaml.safe_dump(payload, default_flow_style=False, sort_keys=False).strip()
    if not compact_yaml:
        return ""
    return f"<project-index>\n{compact_yaml}\n</project-index>"
