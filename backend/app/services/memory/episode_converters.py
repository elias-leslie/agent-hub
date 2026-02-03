"""Episode conversion utilities for MemoryService."""

from typing import Any

from .memory_models import MemoryCategory, MemoryEpisode, MemoryScope
from .memory_utils import map_episode_type


def convert_raw_episode_to_memory_episode(
    ep: Any,
    scope: MemoryScope,
    scope_id: str | None,
) -> MemoryEpisode:
    """
    Convert a raw episode from Graphiti to a MemoryEpisode.

    Args:
        ep: Raw episode object from Graphiti
        scope: Memory scope
        scope_id: Scope identifier

    Returns:
        MemoryEpisode instance
    """
    # Use injection_tier as source of truth; default to REFERENCE
    tier = getattr(ep, "injection_tier", None)
    if tier == "mandate":
        cat = MemoryCategory.MANDATE
    elif tier == "guardrail":
        cat = MemoryCategory.GUARDRAIL
    else:
        cat = MemoryCategory.REFERENCE

    return MemoryEpisode(
        uuid=ep.uuid,
        name=ep.name,
        content=ep.content,
        source=map_episode_type(ep.source),
        category=cat,
        scope=scope,
        scope_id=scope_id,
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
    )


def convert_raw_episodes(
    episodes_raw: list[Any],
    scope: MemoryScope,
    scope_id: str | None,
) -> list[MemoryEpisode]:
    """
    Convert multiple raw episodes to MemoryEpisode objects.

    Args:
        episodes_raw: List of raw episode objects
        scope: Memory scope
        scope_id: Scope identifier

    Returns:
        List of MemoryEpisode instances
    """
    return [convert_raw_episode_to_memory_episode(ep, scope, scope_id) for ep in episodes_raw]
