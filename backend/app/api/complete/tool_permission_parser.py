"""Permission configuration parsing for tool execution."""

from __future__ import annotations

from typing import Any


def parse_claude_permissions(permission_config: dict[str, Any] | None) -> tuple[bool, bool]:
    """Parse permission config and return (yolo_mode, write_enabled) for Claude SDK.

    Args:
        permission_config: Permission configuration dict with mode and allow/deny lists

    Returns:
        Tuple of (yolo_mode, write_enabled)
    """
    yolo_mode = True
    write_enabled = True

    if permission_config and permission_config.get("mode") == "granular":
        yolo_mode = False
        allow_list: set[str] = set(permission_config.get("allow_list", []))
        deny_list: set[str] = set(permission_config.get("deny_list", []))
        write_tools: set[str] = {"write_file", "edit_file", "delete_file", "create_directory"}
        write_enabled = bool(allow_list & write_tools) and not bool(deny_list & write_tools)

    return yolo_mode, write_enabled
