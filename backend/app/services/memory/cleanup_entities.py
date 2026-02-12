"""
Entity cleanup operations.

Handles orphaned entity deletion and duplicate entity consolidation.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Query to merge duplicate entities
_MERGE_DUPLICATES_QUERY = """
UNWIND $delete_uuids AS dup_uuid
MATCH (dup:Entity {uuid: dup_uuid})
MATCH (keep:Entity {uuid: $keep_uuid})

WITH dup, keep

// Move MENTIONS edges: (ep)-[:MENTIONS]->(dup) → (ep)-[:MENTIONS]->(keep)
OPTIONAL MATCH (ep:Episodic)-[m:MENTIONS]->(dup)
WITH dup, keep, collect(ep) AS mentioners
FOREACH (ep IN mentioners |
    MERGE (ep)-[:MENTIONS]->(keep)
)

WITH dup, keep

// Move outgoing RELATES_TO: (dup)-[:RELATES_TO]->(other) → (keep)-[:RELATES_TO]->(other)
OPTIONAL MATCH (dup)-[r_out:RELATES_TO]->(other:Entity)
WHERE other <> keep
WITH dup, keep, collect(other) AS out_targets
FOREACH (other IN out_targets |
    MERGE (keep)-[:RELATES_TO]->(other)
)

WITH dup, keep

// Move incoming RELATES_TO: (other)-[:RELATES_TO]->(dup) → (other)-[:RELATES_TO]->(keep)
OPTIONAL MATCH (other:Entity)-[r_in:RELATES_TO]->(dup)
WHERE other <> keep
WITH dup, keep, collect(other) AS in_sources
FOREACH (other IN in_sources |
    MERGE (other)-[:RELATES_TO]->(keep)
)

DETACH DELETE dup
RETURN count(dup) AS merged
"""


async def cleanup_orphaned_entities(
    driver: Any,
    group_id: str,
) -> dict[str, Any]:
    """
    Delete Entity nodes with no MENTIONS relationships from any Episodic node.

    These accumulate when episodes are deleted but their extracted entities remain.

    Args:
        driver: Neo4j driver instance
        group_id: Group ID to clean up

    Returns:
        Dict with entities_deleted count
    """
    query = """
    MATCH (e:Entity {group_id: $group_id})
    WHERE NOT EXISTS { MATCH (:Episodic)-[:MENTIONS]->(e) }
    DETACH DELETE e
    RETURN count(e) AS deleted
    """

    try:
        records, _, _ = await driver.execute_query(query, group_id=group_id)
        deleted = records[0]["deleted"] if records else 0
        if deleted:
            logger.info("Orphaned entity cleanup: %d entities deleted (group=%s)", deleted, group_id)
        return {"entities_deleted": deleted}
    except Exception as e:
        logger.error("Orphaned entity cleanup failed: %s", e)
        return {"entities_deleted": 0, "error": str(e)}


async def _find_duplicate_entities(driver: Any, group_id: str) -> list[Any]:
    """Find entities with duplicate names in a group."""
    query = """
    MATCH (e:Entity {group_id: $group_id})
    WITH e.name AS name, collect(e) AS entities, count(e) AS cnt
    WHERE cnt > 1
    RETURN name, [e IN entities | e.uuid] AS uuids, cnt
    ORDER BY cnt DESC
    """
    records, _, _ = await driver.execute_query(query, group_id=group_id)
    return records


async def _merge_entity_duplicates(
    driver: Any,
    keep_uuid: str,
    delete_uuids: list[str],
) -> None:
    """Merge duplicate entities into a single entity."""
    await driver.execute_query(
        _MERGE_DUPLICATES_QUERY,
        keep_uuid=keep_uuid,
        delete_uuids=delete_uuids,
    )


async def consolidate_duplicate_entities(
    driver: Any,
    group_id: str,
) -> dict[str, Any]:
    """
    Merge duplicate Entity nodes (same name, same group_id) into one.

    For each set of duplicates, keeps the oldest entity and:
    1. Moves all MENTIONS edges to point to the kept entity
    2. Moves all RELATES_TO edges to reference the kept entity
    3. Deletes the duplicate nodes

    Args:
        driver: Neo4j driver instance
        group_id: Group ID to consolidate within

    Returns:
        Dict with entities_merged, duplicates_found counts
    """
    try:
        records = await _find_duplicate_entities(driver, group_id)

        if not records:
            return {"duplicates_found": 0, "entities_merged": 0}

        total_merged = 0

        for record in records:
            uuids = record["uuids"]
            if len(uuids) < 2:
                continue

            keep_uuid = uuids[0]
            delete_uuids = uuids[1:]
            await _merge_entity_duplicates(driver, keep_uuid, delete_uuids)
            total_merged += len(delete_uuids)

        duplicates_found = len(records)
        if total_merged:
            logger.info(
                "Entity consolidation: %d duplicate names, %d entities merged (group=%s)",
                duplicates_found, total_merged, group_id,
            )
        return {"duplicates_found": duplicates_found, "entities_merged": total_merged}

    except Exception as e:
        logger.error("Entity consolidation failed: %s", e)
        return {"duplicates_found": 0, "entities_merged": 0, "error": str(e)}
