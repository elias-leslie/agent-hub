"""
Memory cleanup operations.

Handles orphaned edge cleanup and stale memory TTL enforcement.
"""

import logging
from datetime import timedelta
from typing import Any

from graphiti_core.utils.datetime_utils import utc_now

from .tracking_operations import validate_episodes

logger = logging.getLogger(__name__)


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
    find_edges_query = """
    MATCH (edge:EntityEdge {group_id: $group_id})
    WHERE edge.episodes IS NOT NULL AND size(edge.episodes) > 0
    RETURN edge.uuid AS edge_uuid, edge.episodes AS episodes
    """

    try:
        records, _, _ = await driver.execute_query(find_edges_query, group_id=group_id)

        if not records:
            return {"edges_updated": 0, "edges_deleted": 0, "stale_refs_removed": 0}

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
        edges_to_update: list[tuple[str, list[str]]] = []
        edges_to_delete: list[str] = []
        stale_refs_removed = 0

        for edge_uuid, episodes in edge_episodes:
            valid_eps = [ep for ep in episodes if ep in valid_episodes]
            stale_count = len(episodes) - len(valid_eps)

            if stale_count > 0:
                stale_refs_removed += stale_count
                if not valid_eps:
                    edges_to_delete.append(edge_uuid)
                else:
                    edges_to_update.append((edge_uuid, valid_eps))

        # Update edges with partial stale refs
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

        # Delete fully orphaned edges
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

    # Check system activity - when was the last episode created?
    activity_query = """
    MATCH (e:Episodic {group_id: $group_id})
    RETURN max(e.created_at) AS last_activity
    """

    try:
        records, _, _ = await driver.execute_query(activity_query, group_id=group_id)

        if records and records[0]["last_activity"]:
            last_activity = records[0]["last_activity"]
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
            return {"deleted": 0, "skipped": True, "reason": "No episodes found in group"}

    except Exception as e:
        logger.error("Failed to check system activity: %s", e)
        return {"deleted": 0, "skipped": True, "reason": f"Activity check failed: {e}"}

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
        logger.info("Cleanup complete for group %s: %d stale memories deleted", group_id, deleted)

        return {"deleted": deleted, "skipped": False, "reason": None}

    except Exception as e:
        logger.error("Cleanup failed: %s", e)
        return {"deleted": 0, "skipped": True, "reason": f"Cleanup query failed: {e}"}
