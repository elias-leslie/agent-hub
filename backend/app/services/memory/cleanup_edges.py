"""
Edge cleanup operations.

Handles orphaned edge cleanup - removing edges with stale episode references.
"""

import logging
from typing import Any

from .tracking_operations import validate_episodes

logger = logging.getLogger(__name__)


def _collect_edge_episodes(records: list[Any]) -> tuple[set[str], list[tuple[str, list[str]]]]:
    """Collect episode UUIDs from edge records."""
    all_episode_uuids: set[str] = set()
    edge_episodes: list[tuple[str, list[str]]] = []

    for record in records:
        edge_uuid = record["edge_uuid"]
        episodes = record["episodes"] or []
        edge_episodes.append((edge_uuid, episodes))
        all_episode_uuids.update(episodes)

    return all_episode_uuids, edge_episodes


def _process_edges(
    edge_episodes: list[tuple[str, list[str]]],
    valid_episodes: set[str],
) -> tuple[list[tuple[str, list[str]]], list[str], int]:
    """Process edges and determine which to update or delete."""
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

    return edges_to_update, edges_to_delete, stale_refs_removed


async def _update_edges(driver: Any, edges: list[tuple[str, list[str]]]) -> None:
    """Update edges with cleaned episode lists."""
    update_query = """
    UNWIND $updates AS update
    MATCH (edge:EntityEdge {uuid: update.uuid})
    SET edge.episodes = update.episodes
    """
    await driver.execute_query(
        update_query,
        updates=[{"uuid": u, "episodes": eps} for u, eps in edges],
    )


async def _delete_edges(driver: Any, edge_uuids: list[str]) -> None:
    """Delete fully orphaned edges."""
    delete_query = """
    UNWIND $uuids AS uuid
    MATCH (edge:EntityEdge {uuid: uuid})
    DETACH DELETE edge
    """
    await driver.execute_query(delete_query, uuids=edge_uuids)


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

        all_episode_uuids, edge_episodes = _collect_edge_episodes(records)
        valid_episodes = await validate_episodes(driver, list(all_episode_uuids))
        edges_to_update, edges_to_delete, stale_refs_removed = _process_edges(
            edge_episodes, valid_episodes
        )

        if edges_to_update:
            await _update_edges(driver, edges_to_update)

        if edges_to_delete:
            await _delete_edges(driver, edges_to_delete)

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
