"""
Session history retrieval operations.

Retrieves recent session episodes with relevant insights and recommendations.
Uses MemoryRepository for PostgreSQL-backed retrieval.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from .memory_models import MemoryCategory, MemoryEpisode, MemoryScope
from .repository import MemoryRepository, get_memory_repository
from .search_helpers import map_tier_to_category

logger = logging.getLogger(__name__)


def _is_relevant_category(tier: int | str | None) -> bool:
    """Check if episode tier maps to a session-relevant category."""
    category = map_tier_to_category(tier)
    return category in {MemoryCategory.REFERENCE, MemoryCategory.GUARDRAIL}


def _convert_memory_to_episode(
    mem_dict: dict[str, Any], scope: MemoryScope, scope_id: str | None
) -> MemoryEpisode:
    """Convert a memory dict to MemoryEpisode."""
    tier = mem_dict.get("tier") or mem_dict.get("injection_tier")
    category = map_tier_to_category(tier)

    return MemoryEpisode(
        uuid=mem_dict.get("uuid", ""),
        name=mem_dict.get("name", ""),
        content=mem_dict.get("content", ""),
        source="text",
        category=category,
        scope=scope,
        scope_id=scope_id,
        source_description=mem_dict.get("source_description", ""),
        created_at=mem_dict.get("created_at") or datetime.now(UTC),
        valid_at=mem_dict.get("valid_at"),
        entities=[],
    )


async def get_session_history(
    group_id: str,
    scope: MemoryScope,
    scope_id: str | None,
    num_sessions: int = 5,
) -> list[MemoryEpisode]:
    """Get recent session recommendations and insights.

    All data is fetched from PostgreSQL via MemoryRepository.
    """
    repo = get_memory_repository()

    # Fetch recent memories for this group, ordered by creation time
    memories = await repo.list_by_scope_and_tier(
        group_id=group_id,
        status="active",
        limit=num_sessions * 10,
        order_by="created_at",
    )

    episodes: list[MemoryEpisode] = []
    for mem in memories:
        mem_dict = MemoryRepository._to_dict(mem)
        tier = mem_dict.get("tier")
        if _is_relevant_category(tier):
            episodes.append(_convert_memory_to_episode(mem_dict, scope, scope_id))
            if len(episodes) >= num_sessions:
                break

    return episodes
