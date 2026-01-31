"""
Episode CRUD and search operations.

Handles fetching, batch operations, and text search for episodes.
"""

import logging
from datetime import datetime
from types import SimpleNamespace
from typing import Any

from .memory_models import MemoryCategory
from .query_builders import (
    EPISODE_FIELDS,
    EPISODE_GET_FIELDS,
    build_category_filter,
    convert_neo4j_datetime,
)

logger = logging.getLogger(__name__)


async def get_episode(
    driver: Any,
    episode_uuid: str,
) -> dict[str, Any] | None:
    """
    Get detailed information about a single episode including usage stats.

    Args:
        driver: Neo4j driver instance
        episode_uuid: UUID of the episode to retrieve

    Returns:
        Dict with episode details and usage stats, or None if not found
    """
    query = f"MATCH (e:Episodic {{uuid: $uuid}}) RETURN {EPISODE_GET_FIELDS}"

    try:
        records, _, _ = await driver.execute_query(query, uuid=episode_uuid)
        if not records:
            return None

        record = records[0]
        return {
            "uuid": record["uuid"],
            "name": record["name"],
            "content": record["content"],
            "injection_tier": record["injection_tier"],
            "source_description": record["source_description"],
            "created_at": convert_neo4j_datetime(record["created_at"]),
            "pinned": record["pinned"],
            "auto_inject": record["auto_inject"],
            "display_order": record["display_order"],
            "trigger_task_types": record["trigger_task_types"],
            "summary": record["summary"],
            "loaded_count": record["loaded_count"],
            "referenced_count": record["referenced_count"],
            "helpful_count": record["helpful_count"],
            "harmful_count": record["harmful_count"],
            "utility_score": record["utility_score"],
        }
    except Exception as e:
        logger.error("Failed to get episode %s: %s", episode_uuid, e)
        return None


async def batch_get_episodes(
    driver: Any,
    episode_uuids: list[str],
) -> dict[str, dict[str, Any]]:
    """
    Get multiple episodes in a single query for efficient batch retrieval.

    Args:
        driver: Neo4j driver instance
        episode_uuids: List of episode UUIDs to retrieve

    Returns:
        Dict mapping UUID to episode details (missing UUIDs not included)
    """
    if not episode_uuids:
        return {}

    query = f"""
    UNWIND $uuids AS uuid
    MATCH (e:Episodic {{uuid: uuid}})
    RETURN {EPISODE_GET_FIELDS}
    """

    try:
        records, _, _ = await driver.execute_query(query, uuids=episode_uuids)
        results: dict[str, dict[str, Any]] = {}

        for record in records:
            results[record["uuid"]] = {
                "uuid": record["uuid"],
                "name": record["name"],
                "content": record["content"],
                "injection_tier": record["injection_tier"],
                "source_description": record["source_description"],
                "created_at": convert_neo4j_datetime(record["created_at"]),
                "pinned": record["pinned"],
                "auto_inject": record["auto_inject"],
                "display_order": record["display_order"],
                "trigger_task_types": record["trigger_task_types"],
                "summary": record["summary"],
                "loaded_count": record["loaded_count"],
                "referenced_count": record["referenced_count"],
                "helpful_count": record["helpful_count"],
                "harmful_count": record["harmful_count"],
                "utility_score": record["utility_score"],
            }

        logger.debug("Batch get: %d/%d episodes found", len(results), len(episode_uuids))
        return results

    except Exception as e:
        logger.error("Failed to batch get episodes: %s", e)
        return {}


def _record_to_episode(rec: dict[str, Any]) -> SimpleNamespace:
    """Convert Neo4j record to Episode-like object."""
    return SimpleNamespace(
        uuid=rec["uuid"],
        name=rec["name"],
        content=rec["content"],
        source=rec["source"],
        source_description=rec["source_description"] or "",
        created_at=convert_neo4j_datetime(rec["created_at"]),
        valid_at=convert_neo4j_datetime(rec["valid_at"]),
        entity_edges=rec["entity_edges"] or [],
        injection_tier=rec["injection_tier"],
        summary=rec["summary"],
        loaded_count=rec["loaded_count"],
        referenced_count=rec["referenced_count"],
        helpful_count=rec["helpful_count"],
        harmful_count=rec["harmful_count"],
        utility_score=rec["utility_score"],
        pinned=rec["pinned"],
    )


async def fetch_episodes_filtered(
    driver: Any,
    group_id: str,
    limit: int,
    reference_time: datetime,
    category: MemoryCategory | None = None,
) -> tuple[list[Any], bool]:
    """
    Fetch episodes with optional category filtering at database level.

    Args:
        driver: Neo4j driver instance
        group_id: Group ID to filter by
        limit: Maximum number of episodes to fetch
        reference_time: Reference time for filtering
        category: Optional category filter

    Returns:
        Tuple of (episodes_list, has_more)
    """
    category_filter = build_category_filter(category.value if category else None)

    query = f"""
    MATCH (e:Episodic)
    WHERE e.group_id = $group_id
      AND e.valid_at <= datetime($reference_time)
      {category_filter}
    RETURN {EPISODE_FIELDS}
    ORDER BY e.valid_at DESC
    LIMIT $limit
    """

    records, _, _ = await driver.execute_query(
        query,
        group_id=group_id,
        reference_time=reference_time.isoformat(),
        limit=limit + 1,
    )

    has_more = len(records) > limit
    episodes = [_record_to_episode(rec) for rec in records[:limit]]
    return episodes, has_more


async def text_search_episodes(
    driver: Any,
    group_id: str,
    query: str,
    limit: int = 50,
    category: MemoryCategory | None = None,
) -> list[Any]:
    """
    Text-based search on episode content, name, summary, and tier.

    Args:
        driver: Neo4j driver instance
        group_id: Group ID to search within
        query: Search query string
        limit: Maximum results to return
        category: Optional category filter

    Returns:
        List of matching episodes
    """
    category_filter = build_category_filter(category.value if category else None)

    search_query = f"""
    MATCH (e:Episodic)
    WHERE e.group_id = $group_id
      AND (
        toLower(e.content) CONTAINS toLower($query)
        OR toLower(coalesce(e.name, '')) CONTAINS toLower($query)
        OR toLower(coalesce(e.summary, '')) CONTAINS toLower($query)
        OR toLower(coalesce(e.injection_tier, '')) CONTAINS toLower($query)
      )
      {category_filter}
    RETURN {EPISODE_FIELDS}
    ORDER BY e.valid_at DESC
    LIMIT $limit
    """

    try:
        records, _, _ = await driver.execute_query(
            search_query,
            group_id=group_id,
            query=query,
            limit=limit,
        )
        return [_record_to_episode(rec) for rec in records]
    except Exception as e:
        logger.error("Text search failed: %s", e)
        return []
