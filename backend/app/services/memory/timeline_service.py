from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from .memory_models import MemoryCategory, MemoryEpisode, MemoryScope
from .memory_utils import build_group_id
from .repository import MemoryRepository, get_memory_repository
from .search_helpers import map_tier_to_category


class TimelineGroup(BaseModel):
    label: str
    date_key: str
    episodes: list[dict[str, Any]]
    count: int


def _classify_date(dt: datetime, now: datetime) -> tuple[str, str]:
    today = now.date()
    episode_date = dt.date()
    delta = (today - episode_date).days

    if delta == 0:
        return "Today", "today"
    if delta == 1:
        return "Yesterday", "yesterday"
    if delta < 7 and episode_date.weekday() < today.weekday():
        return "This Week", "this_week"
    if delta < 7:
        return "Last Week", "last_week"
    if episode_date.year == today.year and episode_date.month == today.month:
        return "This Month", "this_month"
    if delta < 60:
        return "Last Month", "last_month"
    return "Older", "older"


def _memory_to_episode(mem_dict: dict[str, Any], scope: MemoryScope, scope_id: str | None) -> MemoryEpisode:
    """Convert a memory dict to a MemoryEpisode for timeline display."""
    tier = mem_dict.get("tier") or mem_dict.get("injection_tier")
    cat = map_tier_to_category(tier)

    return MemoryEpisode(
        uuid=mem_dict.get("uuid", ""),
        name=mem_dict.get("name", ""),
        content=mem_dict.get("content", ""),
        source="text",
        category=cat,
        scope=scope,
        scope_id=scope_id,
        source_description=mem_dict.get("source_description", ""),
        created_at=mem_dict.get("created_at") or datetime.now(UTC),
        valid_at=mem_dict.get("valid_at"),
        entities=[],
        summary=mem_dict.get("summary"),
        loaded_count=mem_dict.get("loaded_count"),
        referenced_count=mem_dict.get("referenced_count"),
        helpful_count=mem_dict.get("helpful_count"),
        harmful_count=mem_dict.get("harmful_count"),
        utility_score=mem_dict.get("utility_score"),
        pinned=mem_dict.get("pinned"),
        tags=mem_dict.get("tags") or [],
    )


def _episode_to_dict(ep: MemoryEpisode) -> dict[str, Any]:
    return ep.model_dump(mode="json")


async def get_timeline_groups(
    group_id: str,
    scope: MemoryScope | None = None,
    scope_id: str | None = None,
    category: MemoryCategory | None = None,
    limit: int = 10000,
) -> list[TimelineGroup]:
    now = datetime.now(UTC)

    resolved_scope = scope or MemoryScope.GLOBAL
    resolved_group_id = group_id or build_group_id(resolved_scope, scope_id)

    repo = get_memory_repository()

    # Map category to tier for filtering
    tier: int | str | None = None
    if category:
        from .repository import TIER_MAP
        tier = TIER_MAP.get(category.value)

    memories = await repo.list_by_scope_and_tier(
        group_id=resolved_group_id,
        tier=tier,
        status="active",
        limit=limit,
        order_by="created_at",
    )

    episodes = [
        _memory_to_episode(MemoryRepository._to_dict(mem), resolved_scope, scope_id)
        for mem in memories
    ]

    bucket_order = [
        "today",
        "yesterday",
        "this_week",
        "last_week",
        "this_month",
        "last_month",
        "older",
    ]
    buckets: dict[str, list[MemoryEpisode]] = {}
    label_map: dict[str, str] = {}

    for ep in episodes:
        label, key = _classify_date(ep.created_at, now)
        label_map[key] = label
        buckets.setdefault(key, []).append(ep)

    result: list[TimelineGroup] = []
    for key in bucket_order:
        if key in buckets:
            group_episodes = buckets[key]
            result.append(
                TimelineGroup(
                    label=label_map[key],
                    date_key=key,
                    episodes=[_episode_to_dict(ep) for ep in group_episodes],
                    count=len(group_episodes),
                )
            )

    return result
