"""Neo4j query operations for legacy group cleanup."""

from app.services.memory.graphiti_client import GraphitiClient

LEGACY_GROUP_PREFIXES = ["user-", "test-", "session-", "task-"]
LEGACY_GROUP_NAMES = ["default", "none"]


def is_legacy_group(group_id: str) -> bool:
    """Check if a group_id is a legacy group."""
    if group_id in LEGACY_GROUP_NAMES:
        return True
    return any(group_id.startswith(prefix) for prefix in LEGACY_GROUP_PREFIXES)


async def get_group_stats(graphiti: GraphitiClient) -> dict[str, dict]:
    """
    Get episode and entity counts for all legacy groups.

    Returns:
        Dict mapping group_id to stats dict with episode_count and entity_count
    """
    driver = graphiti.driver

    # Get episode counts by group
    episode_query = """
    MATCH (e:Episodic)
    RETURN e.group_id AS group_id, count(e) AS count
    ORDER BY count DESC
    """
    episode_records, _, _ = await driver.execute_query(episode_query)

    # Get entity counts by group
    entity_query = """
    MATCH (e:Entity)
    RETURN e.group_id AS group_id, count(e) AS count
    ORDER BY count DESC
    """
    entity_records, _, _ = await driver.execute_query(entity_query)

    # Combine into a dict
    group_stats: dict[str, dict] = {}
    for record in episode_records:
        group_id = record["group_id"] or "none"
        if is_legacy_group(group_id):
            group_stats[group_id] = {"episode_count": record["count"], "entity_count": 0}

    for record in entity_records:
        group_id = record["group_id"] or "none"
        if is_legacy_group(group_id):
            if group_id not in group_stats:
                group_stats[group_id] = {"episode_count": 0, "entity_count": 0}
            group_stats[group_id]["entity_count"] = record["count"]

    return group_stats


async def get_group_episodes(graphiti: GraphitiClient, group_id: str, limit: int = 50) -> list[dict]:
    """
    Get episodes for a specific group.

    Args:
        graphiti: Graphiti client instance
        group_id: Group ID to query
        limit: Maximum number of episodes to return

    Returns:
        List of episode records
    """
    driver = graphiti.driver

    query = """
    MATCH (e:Episodic {group_id: $group_id})
    RETURN e.uuid AS uuid, e.name AS name, e.content AS content,
           e.created_at AS created_at, e.source_description AS source_description
    ORDER BY e.created_at DESC
    LIMIT $limit
    """
    records, _, _ = await driver.execute_query(query, group_id=group_id, limit=limit)
    return [dict(record) for record in records]


async def delete_group_data(graphiti: GraphitiClient, group_id: str) -> dict:
    """
    Delete all episodes, entities, and edges for a group.

    Args:
        graphiti: Graphiti client instance
        group_id: Group ID to delete

    Returns:
        Dict with deletion counts
    """
    driver = graphiti.driver

    # Delete episodes
    episode_query = """
    MATCH (e:Episodic {group_id: $group_id})
    WITH e
    DETACH DELETE e
    RETURN count(e) AS deleted
    """
    ep_records, _, _ = await driver.execute_query(episode_query, group_id=group_id)
    deleted_episodes = ep_records[0]["deleted"] if ep_records else 0

    # Delete entities
    entity_query = """
    MATCH (e:Entity {group_id: $group_id})
    WITH e
    DETACH DELETE e
    RETURN count(e) AS deleted
    """
    ent_records, _, _ = await driver.execute_query(entity_query, group_id=group_id)
    deleted_entities = ent_records[0]["deleted"] if ent_records else 0

    # Delete edges
    edge_query = """
    MATCH (e:EntityEdge {group_id: $group_id})
    WITH e
    DETACH DELETE e
    RETURN count(e) AS deleted
    """
    edge_records, _, _ = await driver.execute_query(edge_query, group_id=group_id)
    deleted_edges = edge_records[0]["deleted"] if edge_records else 0

    return {
        "deleted_episodes": deleted_episodes,
        "deleted_entities": deleted_entities,
        "deleted_edges": deleted_edges,
    }
