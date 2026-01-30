"""
Neo4j query operations for memory service.

Handles direct database queries for episode validation, access tracking,
batch operations, and cleanup tasks.
"""

import logging
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

from graphiti_core.utils.datetime_utils import utc_now

from .memory_models import MemoryCategory

logger = logging.getLogger(__name__)


async def validate_episodes(
    driver: Any,
    episode_uuids: list[str],
) -> set[str]:
    """
    Validate which episode UUIDs actually exist in the database.

    Args:
        driver: Neo4j driver instance
        episode_uuids: List of episode UUIDs to check

    Returns:
        Set of valid (existing) episode UUIDs
    """
    if not episode_uuids:
        return set()

    # Deduplicate input
    unique_uuids = list(set(episode_uuids))

    query = """
    UNWIND $uuids AS uuid
    MATCH (e:Episodic {uuid: uuid})
    RETURN e.uuid AS uuid
    """

    try:
        records, _, _ = await driver.execute_query(
            query,
            uuids=unique_uuids,
        )
        return {str(r["uuid"]) for r in records}
    except Exception as e:
        logger.warning("Failed to validate episodes: %s", e)
        return set()


async def update_episode_access_time(
    driver: Any,
    episode_uuids: list[str],
) -> None:
    """
    Update loaded_count for accessed episodes (ACE-aligned tracking).

    Args:
        driver: Neo4j driver instance
        episode_uuids: List of episode UUIDs that were accessed
    """
    if not episode_uuids:
        return

    query = """
    UNWIND $uuids AS uuid
    MATCH (e:Episodic {uuid: uuid})
    SET e.loaded_count = coalesce(e.loaded_count, 0) + 1
    """

    try:
        await driver.execute_query(query, uuids=episode_uuids)
        logger.debug("Updated access count for %d episodes", len(episode_uuids))
    except Exception as e:
        logger.warning("Failed to update episode access time: %s", e)


async def update_access_time(
    driver: Any,
    uuids: list[str],
) -> None:
    """
    Update last_accessed_at timestamp for accessed memory items.

    Args:
        driver: Neo4j driver instance
        uuids: List of edge/episode UUIDs that were accessed
    """
    if not uuids:
        return

    now = utc_now().isoformat()

    # Update last_accessed_at on EntityEdge nodes
    query = """
    UNWIND $uuids AS uuid
    MATCH (e:EntityEdge {uuid: uuid})
    SET e.last_accessed_at = datetime($now)
    """

    try:
        await driver.execute_query(query, uuids=uuids, now=now)
        logger.debug("Updated access time for %d items", len(uuids))
    except Exception as e:
        # Don't fail the request if access tracking fails
        logger.warning("Failed to update access time: %s", e)


async def get_episode(
    driver: Any,
    episode_uuid: str,
) -> dict[str, Any] | None:
    """
    Get detailed information about a single episode including usage stats.

    Queries Neo4j directly for full episode properties including
    ACE-aligned usage statistics (helpful_count, harmful_count, etc.).

    Args:
        driver: Neo4j driver instance
        episode_uuid: UUID of the episode to retrieve

    Returns:
        Dict with episode details and usage stats, or None if not found
    """
    query = """
    MATCH (e:Episodic {uuid: $uuid})
    RETURN
        e.uuid AS uuid,
        e.name AS name,
        e.content AS content,
        e.injection_tier AS injection_tier,
        e.source_description AS source_description,
        e.created_at AS created_at,
        coalesce(e.pinned, false) AS pinned,
        coalesce(e.auto_inject, false) AS auto_inject,
        coalesce(e.display_order, 50) AS display_order,
        coalesce(e.trigger_task_types, []) AS trigger_task_types,
        e.summary AS summary,
        coalesce(e.loaded_count, 0) AS loaded_count,
        coalesce(e.referenced_count, 0) AS referenced_count,
        coalesce(e.helpful_count, 0) AS helpful_count,
        coalesce(e.harmful_count, 0) AS harmful_count,
        e.utility_score AS utility_score
    """
    try:
        records, _, _ = await driver.execute_query(
            query,
            uuid=episode_uuid,
        )
        if not records:
            return None

        record = records[0]
        # Convert neo4j DateTime to Python datetime if needed
        created_at = record["created_at"]
        if created_at is not None and hasattr(created_at, "to_native"):
            created_at = created_at.to_native()

        return {
            "uuid": record["uuid"],
            "name": record["name"],
            "content": record["content"],
            "injection_tier": record["injection_tier"],
            "source_description": record["source_description"],
            "created_at": created_at,
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

    query = """
    UNWIND $uuids AS uuid
    MATCH (e:Episodic {uuid: uuid})
    RETURN
        e.uuid AS uuid,
        e.name AS name,
        e.content AS content,
        e.injection_tier AS injection_tier,
        e.source_description AS source_description,
        e.created_at AS created_at,
        coalesce(e.pinned, false) AS pinned,
        coalesce(e.auto_inject, false) AS auto_inject,
        coalesce(e.display_order, 50) AS display_order,
        coalesce(e.trigger_task_types, []) AS trigger_task_types,
        e.summary AS summary,
        coalesce(e.loaded_count, 0) AS loaded_count,
        coalesce(e.referenced_count, 0) AS referenced_count,
        coalesce(e.helpful_count, 0) AS helpful_count,
        coalesce(e.harmful_count, 0) AS harmful_count,
        e.utility_score AS utility_score
    """

    try:
        records, _, _ = await driver.execute_query(
            query,
            uuids=episode_uuids,
        )

        results: dict[str, dict[str, Any]] = {}
        for record in records:
            created_at = record["created_at"]
            if created_at is not None and hasattr(created_at, "to_native"):
                created_at = created_at.to_native()

            results[record["uuid"]] = {
                "uuid": record["uuid"],
                "name": record["name"],
                "content": record["content"],
                "injection_tier": record["injection_tier"],
                "source_description": record["source_description"],
                "created_at": created_at,
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


async def cleanup_orphaned_edges(
    driver: Any,
    group_id: str,
) -> dict[str, Any]:
    """
    Clean up edges with stale episode references.

    Graphiti's remove_episode only removes edges where the deleted episode
    is the FIRST in the episodes[] list. This leaves orphaned edges when
    an episode appears later in the list.

    This cleanup:
    1. Finds edges with episode references that no longer exist
    2. Removes stale episode UUIDs from edges
    3. Deletes edges where all episodes have been removed

    Args:
        driver: Neo4j driver instance
        group_id: Group ID to clean up

    Returns:
        Dict with cleanup results: edges_updated, edges_deleted, stale_refs_removed
    """
    # Step 1: Find all edges with episode references in this group
    find_edges_query = """
    MATCH (edge:EntityEdge {group_id: $group_id})
    WHERE edge.episodes IS NOT NULL AND size(edge.episodes) > 0
    RETURN edge.uuid AS edge_uuid, edge.episodes AS episodes
    """

    try:
        records, _, _ = await driver.execute_query(
            find_edges_query,
            group_id=group_id,
        )

        if not records:
            return {
                "edges_updated": 0,
                "edges_deleted": 0,
                "stale_refs_removed": 0,
            }

        # Collect all episode UUIDs to validate
        all_episode_uuids: set[str] = set()
        edge_episodes: list[tuple[str, list[str]]] = []

        for record in records:
            edge_uuid = record["edge_uuid"]
            episodes = record["episodes"] or []
            edge_episodes.append((edge_uuid, episodes))
            all_episode_uuids.update(episodes)

        # Validate which episodes exist
        valid_episodes = await validate_episodes(driver, list(all_episode_uuids))

        # Process edges
        edges_to_update: list[tuple[str, list[str]]] = []  # (edge_uuid, valid_episodes)
        edges_to_delete: list[str] = []
        stale_refs_removed = 0

        for edge_uuid, episodes in edge_episodes:
            valid_eps = [ep for ep in episodes if ep in valid_episodes]
            stale_count = len(episodes) - len(valid_eps)

            if stale_count > 0:
                stale_refs_removed += stale_count
                if not valid_eps:
                    # All episodes removed - delete edge
                    edges_to_delete.append(edge_uuid)
                else:
                    # Some episodes remain - update edge
                    edges_to_update.append((edge_uuid, valid_eps))

        # Step 2: Update edges with partial stale refs
        if edges_to_update:
            update_query = """
            UNWIND $updates AS update
            MATCH (edge:EntityEdge {uuid: update.uuid})
            SET edge.episodes = update.episodes
            """
            await driver.execute_query(
                update_query,
                updates=[{"uuid": u, "episodes": eps} for u, eps in edges_to_update],
            )

        # Step 3: Delete fully orphaned edges
        if edges_to_delete:
            delete_query = """
            UNWIND $uuids AS uuid
            MATCH (edge:EntityEdge {uuid: uuid})
            DETACH DELETE edge
            """
            await driver.execute_query(delete_query, uuids=edges_to_delete)

        result = {
            "edges_updated": len(edges_to_update),
            "edges_deleted": len(edges_to_delete),
            "stale_refs_removed": stale_refs_removed,
        }

        logger.info(
            "Orphaned edge cleanup: %d updated, %d deleted, %d stale refs",
            result["edges_updated"],
            result["edges_deleted"],
            result["stale_refs_removed"],
        )

        return result

    except Exception as e:
        logger.error("Orphaned edge cleanup failed: %s", e)
        return {
            "edges_updated": 0,
            "edges_deleted": 0,
            "stale_refs_removed": 0,
            "error": str(e),
        }


async def fetch_episodes_filtered(
    driver: Any,
    group_id: str,
    limit: int,
    reference_time: datetime,
    category: MemoryCategory | None = None,
) -> tuple[list[Any], bool]:
    """
    Fetch episodes with optional category filtering at database level.

    Uses the injection_tier field for filtering, which is the source of truth
    for episode categorization (matches context_injector.get_episodes_by_tier).

    Args:
        driver: Neo4j driver instance
        group_id: Group ID to filter by
        limit: Maximum number of episodes to fetch
        reference_time: Reference time for filtering
        category: Optional category filter

    Returns:
        Tuple of (episodes_list, has_more)
    """
    # Filter by injection_tier field - this is the source of truth
    # Same approach as context_injector.get_episodes_by_tier()
    category_filter = ""
    if category:
        category_filter = f"AND e.injection_tier = '{category.value}'"

    query = f"""
    MATCH (e:Episodic)
    WHERE e.group_id = $group_id
      AND e.valid_at <= datetime($reference_time)
      {category_filter}
    RETURN e.uuid AS uuid,
           e.name AS name,
           e.content AS content,
           e.source AS source,
           e.source_description AS source_description,
           e.created_at AS created_at,
           e.valid_at AS valid_at,
           e.entity_edges AS entity_edges,
           e.injection_tier AS injection_tier,
           e.summary AS summary,
           coalesce(e.loaded_count, 0) AS loaded_count,
           coalesce(e.referenced_count, 0) AS referenced_count,
           coalesce(e.helpful_count, 0) AS helpful_count,
           coalesce(e.harmful_count, 0) AS harmful_count,
           e.utility_score AS utility_score
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
    records = records[:limit]

    # Convert Neo4j records to Episode-like objects
    episodes = []
    for rec in records:
        # Convert Neo4j DateTime to Python datetime
        created_at = rec["created_at"]
        if hasattr(created_at, "to_native"):
            created_at = created_at.to_native()

        valid_at = rec["valid_at"]
        if hasattr(valid_at, "to_native"):
            valid_at = valid_at.to_native()

        ep = SimpleNamespace(
            uuid=rec["uuid"],
            name=rec["name"],
            content=rec["content"],
            source=rec["source"],
            source_description=rec["source_description"] or "",
            created_at=created_at,
            valid_at=valid_at,
            entity_edges=rec["entity_edges"] or [],
            injection_tier=rec["injection_tier"],
            summary=rec["summary"],
            loaded_count=rec["loaded_count"],
            referenced_count=rec["referenced_count"],
            helpful_count=rec["helpful_count"],
            harmful_count=rec["harmful_count"],
            utility_score=rec["utility_score"],
        )
        episodes.append(ep)

    return episodes, has_more


async def cleanup_stale_memories(
    driver: Any,
    group_id: str,
    ttl_days: int = 30,
) -> dict[str, Any]:
    """
    Clean up memories that haven't been accessed within TTL period.

    Implements system activity safeguard: if the system itself hasn't been
    active for 30+ days (no new episodes), cleanup is skipped to prevent
    accidental mass deletion when system resumes.

    Args:
        driver: Neo4j driver instance
        group_id: Group ID to clean up
        ttl_days: Days without access before memory is considered stale

    Returns:
        Dict with cleanup results: deleted count, skipped, and reason
    """
    now = utc_now()

    # First, check system activity - when was the last episode created?
    activity_query = """
    MATCH (e:Episodic {group_id: $group_id})
    RETURN max(e.created_at) AS last_activity
    """

    try:
        records, _, _ = await driver.execute_query(
            activity_query,
            group_id=group_id,
        )

        if records and records[0]["last_activity"]:
            last_activity = records[0]["last_activity"]
            # Neo4j returns datetime as neo4j.time.DateTime, convert to Python
            if hasattr(last_activity, "to_native"):
                last_activity = last_activity.to_native()

            days_inactive = (now - last_activity).days

            if days_inactive >= ttl_days:
                logger.warning(
                    "System inactive for %d days, skipping cleanup to prevent mass deletion",
                    days_inactive,
                )
                return {
                    "deleted": 0,
                    "skipped": True,
                    "reason": f"System inactive for {days_inactive} days - cleanup skipped as safeguard",
                }
        else:
            # No episodes found
            return {
                "deleted": 0,
                "skipped": True,
                "reason": "No episodes found in group",
            }

    except Exception as e:
        logger.error("Failed to check system activity: %s", e)
        return {
            "deleted": 0,
            "skipped": True,
            "reason": f"Activity check failed: {e}",
        }

    # Find and delete stale edges (not accessed within TTL)
    cutoff = now - timedelta(days=ttl_days)

    cleanup_query = """
    MATCH (e:EntityEdge {group_id: $group_id})
    WHERE e.last_accessed_at IS NOT NULL
      AND e.last_accessed_at < datetime($cutoff)
    WITH e LIMIT 100
    DETACH DELETE e
    RETURN count(e) AS deleted
    """

    try:
        records, _, _ = await driver.execute_query(
            cleanup_query,
            group_id=group_id,
            cutoff=cutoff.isoformat(),
        )

        deleted = records[0]["deleted"] if records else 0
        logger.info(
            "Cleanup complete for group %s: %d stale memories deleted",
            group_id,
            deleted,
        )

        return {
            "deleted": deleted,
            "skipped": False,
            "reason": None,
        }

    except Exception as e:
        logger.error("Cleanup failed: %s", e)
        return {
            "deleted": 0,
            "skipped": True,
            "reason": f"Cleanup query failed: {e}",
        }
