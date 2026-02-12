"""
Semantic search operations using Graphiti vector search.

Handles episode-based semantic search with deduplication and validation.
"""

import logging
from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from graphiti_core import Graphiti
else:
    Graphiti = None

from .memory_models import MemoryScope, MemorySearchResult, MemorySource
from .memory_queries import (
    update_episode_access_time,
    validate_episodes_with_content,
)
from .search_helpers import extract_episode_candidates

logger = logging.getLogger(__name__)


def _create_search_result(
    ep_uuid: str, score: float, fact: str, created: object | datetime, body: str, scope: MemoryScope
) -> MemorySearchResult:
    """Create a single search result from episode data."""
    created_dt = created if isinstance(created, datetime) else datetime.now()
    return MemorySearchResult(
        uuid=ep_uuid,
        content=body or fact,
        source=MemorySource.CHAT,
        relevance_score=score,
        created_at=created_dt,
        facts=[fact] if fact else [],
        scope=scope,
    )


def _build_search_results(
    episode_candidates: Sequence[tuple[str, float, str, object | datetime]],
    episode_bodies: dict[str, str],
    scope: MemoryScope,
    limit: int,
) -> tuple[list[MemorySearchResult], list[str]]:
    """Build deduplicated search results from episode candidates."""
    search_results: list[MemorySearchResult] = []
    seen_uuids: set[str] = set()
    valid_episode_uuids: list[str] = []

    for ep_uuid, score, fact, created in episode_candidates:
        if ep_uuid not in episode_bodies or ep_uuid in seen_uuids:
            continue

        seen_uuids.add(ep_uuid)
        result = _create_search_result(ep_uuid, score, fact, created, episode_bodies[ep_uuid], scope)
        search_results.append(result)
        valid_episode_uuids.append(ep_uuid)

        if len(search_results) >= limit:
            break

    return search_results, valid_episode_uuids


async def search_memory(
    graphiti: "Graphiti",
    group_id: str | None,
    scope: MemoryScope,
    query: str,
    limit: int = 10,
    min_score: float = 0.0,
) -> list[MemorySearchResult]:
    """
    Search memory for relevant episodes and facts.

    Returns episode UUIDs (not edge UUIDs) for compatibility with get_episode().
    Validates episode existence and deduplicates by episode UUID.

    Args:
        group_id: Group ID to search within (None = search all groups).
    """
    group_ids = [group_id] if group_id else None
    edges = await graphiti.search(
        query=query, group_ids=group_ids, num_results=limit * 3
    )

    episode_candidates = extract_episode_candidates(edges, min_score)
    episode_bodies = await validate_episodes_with_content(
        graphiti.driver, [c[0] for c in episode_candidates]
    )

    search_results, valid_uuids = _build_search_results(
        episode_candidates, episode_bodies, scope, limit
    )

    if valid_uuids:
        await update_episode_access_time(graphiti.driver, valid_uuids)

    return search_results
