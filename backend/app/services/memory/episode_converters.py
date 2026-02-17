"""Episode conversion utilities for MemoryService."""

from typing import Any

from .memory_models import MemoryEpisode, MemoryScope
from .memory_utils import map_episode_type, parse_group_id
from .search_helpers import map_tier_to_category


def convert_raw_episode_to_memory_episode(
    ep: Any,
    scope: MemoryScope | None = None,
    scope_id: str | None = None,
) -> MemoryEpisode:
    """
    Convert a raw episode from Graphiti to a MemoryEpisode.

    Scope is derived from the episode's group_id when available.
    Falls back to the provided scope/scope_id if group_id is absent.

    Args:
        ep: Raw episode object from Graphiti
        scope: Fallback memory scope (used when group_id not present)
        scope_id: Fallback scope identifier

    Returns:
        MemoryEpisode instance
    """
    # Derive scope from group_id on the episode itself
    group_id = getattr(ep, "group_id", None)
    if group_id:
        resolved_scope, resolved_scope_id = parse_group_id(group_id)
    else:
        resolved_scope = scope or MemoryScope.GLOBAL
        resolved_scope_id = scope_id

    # Use injection_tier as source of truth; default to REFERENCE
    tier = getattr(ep, "injection_tier", None)
    cat = map_tier_to_category(tier)

    return MemoryEpisode(
        uuid=ep.uuid,
        name=ep.name,
        content=ep.content,
        source=map_episode_type(ep.source),
        category=cat,
        scope=resolved_scope,
        scope_id=resolved_scope_id,
        source_description=ep.source_description,
        created_at=ep.created_at,
        valid_at=ep.valid_at,
        entities=ep.entity_edges,
        summary=getattr(ep, "summary", None),
        loaded_count=getattr(ep, "loaded_count", None),
        referenced_count=getattr(ep, "referenced_count", None),
        helpful_count=getattr(ep, "helpful_count", None),
        harmful_count=getattr(ep, "harmful_count", None),
        utility_score=getattr(ep, "utility_score", None),
        pinned=getattr(ep, "pinned", None),
        tags=getattr(ep, "tags", None) or [],
    )


def convert_raw_episodes(
    episodes_raw: list[Any],
    scope: MemoryScope | None = None,
    scope_id: str | None = None,
) -> list[MemoryEpisode]:
    """
    Convert multiple raw episodes to MemoryEpisode objects.

    Scope is derived per-episode from group_id. The scope/scope_id params
    are only used as fallback when an episode lacks a group_id.

    Args:
        episodes_raw: List of raw episode objects
        scope: Fallback memory scope
        scope_id: Fallback scope identifier

    Returns:
        List of MemoryEpisode instances
    """
    return [convert_raw_episode_to_memory_episode(ep, scope, scope_id) for ep in episodes_raw]
