"""Change detection logic for memory import."""

from __future__ import annotations

from typing import Any

from ._api_paths import MEMORY_LIST_PATH
from .memory_api import agent_hub_request


def fetch_current_episodes() -> dict[str, dict[str, Any]]:
    """Fetch current episodes from memory system."""
    params: dict[str, Any] = {"limit": 300}
    current_episodes: list[dict[str, Any]] = []

    while True:
        current_result = agent_hub_request(
            "GET",
            MEMORY_LIST_PATH,
            params=params,
            tool_name="st memory import",
        )
        current_episodes.extend(current_result.get("episodes", []))
        if not current_result.get("has_more") or not current_result.get("cursor"):
            break
        params["cursor"] = current_result["cursor"]

    return {str(ep["uuid"]): ep for ep in current_episodes if ep.get("uuid")}


def detect_content_changes(
    imported_by_uuid: dict[str, dict[str, Any]],
    current_by_uuid: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Detect episodes where content has changed."""
    content_changes: list[dict[str, Any]] = []

    for uuid, imported_ep in imported_by_uuid.items():
        current_ep = current_by_uuid.get(uuid)
        if not current_ep:
            continue

        imported_content = imported_ep.get("content", "")
        current_content = current_ep.get("content", "")

        if imported_content != current_content:
            content_changes.append({
                "uuid": uuid,
                "old_content": current_content,
                "new_content": imported_content,
                "name": current_ep.get("name", "imported_episode"),
                "tier": imported_ep.get("category") or current_ep.get("injection_tier", "reference"),
            })

    return content_changes


def detect_property_updates(
    imported_by_uuid: dict[str, dict[str, Any]],
    current_by_uuid: dict[str, dict[str, Any]],
    content_changes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Detect episodes where properties (but not content) have changed."""
    content_change_uuids = {c["uuid"] for c in content_changes}
    property_updates: list[dict[str, Any]] = []

    for uuid, imported_ep in imported_by_uuid.items():
        if uuid in content_change_uuids:
            continue

        current_ep = current_by_uuid.get(uuid)
        if not current_ep:
            continue

        update: dict[str, Any] = {"uuid": uuid}

        imported_tier = imported_ep.get("injection_tier") or imported_ep.get("category")
        current_tier = current_ep.get("injection_tier") or current_ep.get("category")
        if imported_tier and imported_tier != current_tier:
            update["injection_tier"] = imported_tier
        if imported_ep.get("summary") is not None and imported_ep.get("summary") != current_ep.get("summary"):
            update["summary"] = imported_ep["summary"]
        if imported_ep.get("trigger_task_types") is not None and list(imported_ep.get("trigger_task_types") or []) != list(current_ep.get("trigger_task_types") or []):
            update["trigger_task_types"] = imported_ep["trigger_task_types"]
        if imported_ep.get("pinned") is not None and imported_ep.get("pinned") != current_ep.get("pinned"):
            update["pinned"] = imported_ep["pinned"]
        if imported_ep.get("auto_inject") is not None and imported_ep.get("auto_inject") != current_ep.get("auto_inject"):
            update["auto_inject"] = imported_ep["auto_inject"]
        if imported_ep.get("display_order") is not None and imported_ep.get("display_order") != current_ep.get("display_order"):
            update["display_order"] = imported_ep["display_order"]

        if len(update) > 1:
            property_updates.append(update)

    return property_updates
