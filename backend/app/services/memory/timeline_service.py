from datetime import datetime
from typing import Any

from pydantic import BaseModel

from .episode_converters import convert_raw_episodes
from .memory_models import MemoryCategory, MemoryEpisode, MemoryScope
from .memory_queries import fetch_episodes_filtered
from .memory_utils import build_group_id


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


def _episode_to_dict(ep: MemoryEpisode) -> dict[str, Any]:
    return ep.model_dump(mode="json")


async def get_timeline_groups(
    group_id: str,
    scope: MemoryScope | None = None,
    scope_id: str | None = None,
    category: MemoryCategory | None = None,
    limit: int = 200,
) -> list[TimelineGroup]:
    from graphiti_core.utils.datetime_utils import utc_now

    from .graphiti_client import get_graphiti

    graphiti = get_graphiti()
    now = utc_now()

    resolved_scope = scope or MemoryScope.GLOBAL
    resolved_group_id = group_id or build_group_id(resolved_scope, scope_id)

    episodes_raw, _ = await fetch_episodes_filtered(
        graphiti.driver, resolved_group_id, limit, now, category
    )

    episodes = convert_raw_episodes(episodes_raw, resolved_scope, scope_id)

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
