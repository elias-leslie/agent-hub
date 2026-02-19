"""
Episode CRUD and search operations.

Handles fetching, batch operations, and text search for episodes.
"""

import logging
from datetime import datetime
from typing import Any

from .episode_operations_helpers import record_to_episode, record_to_get_dict
from .memory_models import MemoryCategory
from .query_builders import EPISODE_FIELDS, EPISODE_GET_FIELDS, build_category_filter

logger = logging.getLogger(__name__)

# Private alias preserved for any internal callers.
_record_to_episode = record_to_episode


async def get_episode(driver: Any, episode_uuid: str) -> dict[str, Any] | None:
    """Get detailed information about a single episode including usage stats."""
    query = f"MATCH (e:Episodic {{uuid: $uuid}}) RETURN {EPISODE_GET_FIELDS}"
    try:
        records, _, _ = await driver.execute_query(query, uuid=episode_uuid)
        return record_to_get_dict(records[0]) if records else None
    except Exception as e:
        logger.error("Failed to get episode %s: %s", episode_uuid, e)
        return None


async def batch_get_episodes(
    driver: Any, episode_uuids: list[str]
) -> dict[str, dict[str, Any]]:
    """Get multiple episodes in a single query for efficient batch retrieval."""
    if not episode_uuids:
        return {}
    query = f"""
    UNWIND $uuids AS uuid
    MATCH (e:Episodic {{uuid: uuid}})
    RETURN {EPISODE_GET_FIELDS}
    """
    try:
        records, _, _ = await driver.execute_query(query, uuids=episode_uuids)
        results = {rec["uuid"]: record_to_get_dict(rec) for rec in records}
        logger.debug("Batch get: %d/%d episodes found", len(results), len(episode_uuids))
        return results
    except Exception as e:
        logger.error("Failed to batch get episodes: %s", e)
        return {}


async def fetch_episodes_filtered(
    driver: Any,
    group_id: str | None,
    limit: int,
    reference_time: datetime,
    category: MemoryCategory | None = None,
) -> tuple[list[Any], bool]:
    """Fetch episodes with optional category filtering at database level."""
    category_filter = build_category_filter(category.value if category else None)
    group_filter = "AND e.group_id = $group_id" if group_id else ""
    query = f"""
    MATCH (e:Episodic)
    WHERE COALESCE(e.vector_indexed, true) = true
      AND e.valid_at <= datetime($reference_time)
      {group_filter}
      {category_filter}
    RETURN {EPISODE_FIELDS}
    ORDER BY e.valid_at DESC
    LIMIT $limit
    """
    params: dict[str, Any] = {
        "reference_time": reference_time.isoformat(),
        "limit": limit + 1,
    }
    if group_id:
        params["group_id"] = group_id
    records, _, _ = await driver.execute_query(query, **params)
    has_more = len(records) > limit
    return [record_to_episode(rec) for rec in records[:limit]], has_more


async def text_search_episodes(
    driver: Any,
    group_id: str | None,
    query: str,
    limit: int = 50,
    category: MemoryCategory | None = None,
) -> list[Any]:
    """Text-based search on episode content, name, summary, and tier."""
    category_filter = build_category_filter(category.value if category else None)
    group_filter = "AND e.group_id = $group_id" if group_id else ""
    search_query = f"""
    MATCH (e:Episodic)
    WHERE COALESCE(e.vector_indexed, true) = true
      AND (
        toLower(e.content) CONTAINS toLower($query)
        OR toLower(coalesce(e.name, '')) CONTAINS toLower($query)
        OR toLower(coalesce(e.summary, '')) CONTAINS toLower($query)
        OR toLower(coalesce(e.injection_tier, '')) CONTAINS toLower($query)
      )
      {group_filter}
      {category_filter}
    RETURN {EPISODE_FIELDS}
    ORDER BY e.valid_at DESC
    LIMIT $limit
    """
    params: dict[str, Any] = {"query": query, "limit": limit}
    if group_id:
        params["group_id"] = group_id
    try:
        records, _, _ = await driver.execute_query(search_query, **params)
        return [record_to_episode(rec) for rec in records]
    except Exception as e:
        logger.error("Text search failed: %s", e)
        return []
