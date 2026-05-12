"""
Utility functions for memory service.

Contains helper functions for group ID building, UUID resolution, and type mapping.
"""

import logging
from typing import Any

from .memory_models import MemoryScope, MemorySource

logger = logging.getLogger(__name__)


def parse_group_id(group_id: str | None) -> tuple[MemoryScope, str | None]:
    """
    Derive (scope, scope_id) from a group_id.

    Inverse of build_group_id. Returns (GLOBAL, None) for "global" or unknown formats.

    Args:
        group_id: Group ID string (e.g. "global", "project-agent-hub")

    Returns:
        Tuple of (MemoryScope, scope_id)
    """
    if not group_id or group_id == "global":
        return MemoryScope.GLOBAL, None

    if group_id.startswith("project-"):
        return MemoryScope.PROJECT, group_id[len("project-"):]

    return MemoryScope.GLOBAL, None


def build_group_id(scope: MemoryScope, scope_id: str | None = None) -> str:
    """
    Build group_id from scope and scope_id.

    This is the canonical implementation - use this instead of duplicating logic.
    Only allows alphanumeric, dashes, and underscores in group_id.

    Args:
        scope: Memory scope (GLOBAL, PROJECT)
        scope_id: Identifier for the scope (project_id)

    Returns:
        Sanitized group_id string
    """
    if scope == MemoryScope.GLOBAL:
        return "global"

    # Sanitize scope_id: replace invalid characters with dashes
    safe_id = (scope_id or "default").replace(":", "-").replace("/", "-")

    if scope == MemoryScope.PROJECT:
        return f"project-{safe_id}"

    # Should not reach here with current enum values
    raise ValueError(f"Unknown scope: {scope}")


async def resolve_uuid_prefix_with_driver(
    driver: Any = None,
    uuid_or_prefix: str = "",
    group_id: str | None = None,
) -> str:
    """
    Resolve a UUID prefix (8-char) or full UUID to a full UUID.

    Args:
        driver: Unused (kept for backward compatibility). Pass None.
        uuid_or_prefix: Either a full UUID or an 8-char prefix
        group_id: Group ID for scoping (None = search all groups)

    Returns:
        Full UUID string

    Raises:
        ValueError: If prefix is ambiguous (multiple matches) or not found
    """
    del driver
    from .repository import get_memory_repository

    repo = get_memory_repository()
    return await repo.resolve_uuid_prefix(uuid_or_prefix, group_id=group_id)


async def resolve_uuid_prefix(
    uuid_or_prefix: str,
    group_id: str | None = None,
) -> str:
    """
    Resolve a UUID prefix (8-char) or full UUID to a full UUID.

    Args:
        uuid_or_prefix: Either a full UUID or an 8-char prefix
        group_id: Group ID for scoping (None = search all groups)

    Returns:
        Full UUID string

    Raises:
        ValueError: If prefix is ambiguous (multiple matches) or not found
    """
    from .repository import get_memory_repository

    repo = get_memory_repository()
    return await repo.resolve_uuid_prefix(uuid_or_prefix, group_id=group_id)


def map_episode_type(ep_type: Any) -> MemorySource:
    """
    Map an episode type to our MemorySource.

    Maps a source type string to MemorySource.

    Args:
        ep_type: Episode type value (string or enum)

    Returns:
        Corresponding MemorySource enum value
    """
    ep_str = str(ep_type).lower() if ep_type else ""
    if ep_str in ("message", "chat"):
        return MemorySource.CHAT
    elif ep_str in ("voice", "audio"):
        return MemorySource.VOICE
    return MemorySource.SYSTEM
