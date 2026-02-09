"""Neo4j query builders for episode auditing."""

from typing import Any


def build_episode_query(group_filter: str | None = None) -> tuple[str, dict[str, Any]]:
    """
    Build Neo4j query to fetch episodes.

    Args:
        group_filter: Optional group_id to filter by

    Returns:
        Tuple of (query string, parameters dict)
    """
    base_query = """
    MATCH (e:Episodic {FILTER})
    RETURN e.uuid AS uuid, e.name AS name, e.content AS content,
           e.group_id AS group_id, e.created_at AS created_at,
           e.source_description AS source_description,
           e.entity_edges AS entity_edges
    ORDER BY e.created_at DESC
    """

    if group_filter:
        query = base_query.replace("{FILTER}", "group_id: $group_id")
        params = {"group_id": group_filter}
    else:
        query = base_query.replace(" {FILTER}", "")
        params = {}

    return query, params
