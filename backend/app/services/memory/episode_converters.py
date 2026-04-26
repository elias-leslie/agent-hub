"""Episode conversion utilities for MemoryService.

Converts raw memory data (dicts from MemoryRepository._to_dict() or
SimpleNamespace objects from record_to_episode()) to MemoryEpisode objects.
"""

from typing import Any

from .applicability import normalize_applicability, normalize_context_kind
from .memory_models import MemoryEpisode, MemoryScope, MemorySource
from .memory_utils import parse_group_id
from .search_helpers import map_tier_to_category


def _get_attr_or_key(obj: Any, name: str, default: Any = None) -> Any:
    """Get value from an object by attribute or dict key."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _map_source(source: Any) -> MemorySource:
    """Map a source value to MemorySource enum.

    Handles string values from the database (e.g., 'text', 'message', 'chat')
    and MemorySource enum values.
    """
    if isinstance(source, MemorySource):
        return source
    source_str = str(source) if source else ""
    if source_str in ("message", "chat"):
        return MemorySource.CHAT
    if source_str == "voice":
        return MemorySource.VOICE
    return MemorySource.SYSTEM


def convert_raw_episode_to_memory_episode(
    ep: Any,
    scope: MemoryScope | None = None,
    scope_id: str | None = None,
) -> MemoryEpisode:
    """
    Convert a raw memory record to a MemoryEpisode.

    Accepts either a dict (from MemoryRepository._to_dict()) or an object
    with attributes (SimpleNamespace from record_to_episode(), or ORM Memory).

    Scope is derived from the record's group_id when available.
    Falls back to the provided scope/scope_id if group_id is absent.

    Args:
        ep: Raw memory record (dict or object with attributes)
        scope: Fallback memory scope (used when group_id not present)
        scope_id: Fallback scope identifier

    Returns:
        MemoryEpisode instance
    """
    # Derive scope from group_id on the record itself
    group_id = _get_attr_or_key(ep, "group_id")
    if group_id:
        resolved_scope, resolved_scope_id = parse_group_id(group_id)
    else:
        raw_scope = _get_attr_or_key(ep, "scope")
        try:
            resolved_scope = MemoryScope(str(raw_scope))
        except ValueError:
            resolved_scope = scope or MemoryScope.GLOBAL
        resolved_scope_id = _get_attr_or_key(ep, "scope_id", None) or scope_id

    # Use injection_tier as source of truth; default to REFERENCE
    tier = _get_attr_or_key(ep, "injection_tier")
    cat = map_tier_to_category(tier)

    # Extract source and map to MemorySource enum
    raw_source = _get_attr_or_key(ep, "source") or _get_attr_or_key(ep, "memory_type")
    mapped_source = _map_source(raw_source)

    created_at = _get_attr_or_key(ep, "created_at")
    updated_at = _get_attr_or_key(ep, "updated_at") or created_at
    valid_at = _get_attr_or_key(ep, "valid_at") or created_at

    return MemoryEpisode(
        uuid=str(_get_attr_or_key(ep, "uuid") or _get_attr_or_key(ep, "id") or ""),
        name=_get_attr_or_key(ep, "name") or "",
        content=_get_attr_or_key(ep, "content") or "",
        source=mapped_source,
        category=cat,
        scope=resolved_scope,
        scope_id=resolved_scope_id,
        source_description=_get_attr_or_key(ep, "source_description") or "",
        created_at=created_at,
        updated_at=updated_at,
        valid_at=valid_at,
        entities=_get_attr_or_key(ep, "entity_edges") or [],
        summary=_get_attr_or_key(ep, "summary"),
        review_status=_get_attr_or_key(ep, "review_status") or "pending",
        sensitivity_tier=_get_attr_or_key(ep, "sensitivity_tier") or "normal",
        last_reviewed_at=_get_attr_or_key(ep, "last_reviewed_at"),
        loaded_count=_get_attr_or_key(ep, "loaded_count"),
        referenced_count=_get_attr_or_key(ep, "referenced_count"),
        helpful_count=_get_attr_or_key(ep, "helpful_count"),
        harmful_count=_get_attr_or_key(ep, "harmful_count"),
        utility_score=_get_attr_or_key(ep, "utility_score"),
        pinned=_get_attr_or_key(ep, "pinned"),
        tags=_get_attr_or_key(ep, "tags") or [],
        trigger_task_types=_get_attr_or_key(ep, "trigger_task_types") or [],
        trigger_phases=_get_attr_or_key(ep, "trigger_phases") or [],
        context_kind=normalize_context_kind(
            _get_attr_or_key(ep, "context_kind"),
            memory_type=_get_attr_or_key(ep, "memory_type"),
            tier=_get_attr_or_key(ep, "tier") or tier,
        ),
        applicability=normalize_applicability(_get_attr_or_key(ep, "applicability")),
    )


def convert_raw_episodes(
    episodes_raw: list[Any],
    scope: MemoryScope | None = None,
    scope_id: str | None = None,
) -> list[MemoryEpisode]:
    """
    Convert multiple raw memory records to MemoryEpisode objects.

    Scope is derived per-record from group_id. The scope/scope_id params
    are only used as fallback when a record lacks a group_id.

    Args:
        episodes_raw: List of raw memory records (dicts or objects)
        scope: Fallback memory scope
        scope_id: Fallback scope identifier

    Returns:
        List of MemoryEpisode instances
    """
    return [convert_raw_episode_to_memory_episode(ep, scope, scope_id) for ep in episodes_raw]
