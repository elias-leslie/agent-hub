"""
Neo4j query operations for adaptive index.

Handles fetching mandate data and usage statistics.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def fetch_mandates_with_stats() -> tuple[list[dict[str, Any]], dict[str, dict[str, int]]]:
    """
    Fetch mandates and their usage stats from Neo4j.

    Returns:
        Tuple of (golden_standards, usage_stats)
        - golden_standards: List of mandate dicts
        - usage_stats: Dict of {uuid: {loaded_count, referenced_count}}
    """
    from .graphiti_client import get_graphiti

    try:
        graphiti = get_graphiti()
        driver = graphiti.driver
        query = """
        MATCH (e:Episodic {group_id: 'global'})
        WHERE e.injection_tier = 'mandate'
        RETURN e.uuid AS uuid, e.content AS content, e.source_description AS source_description,
               COALESCE(e.loaded_count, 0) AS loaded_count, COALESCE(e.referenced_count, 0) AS referenced_count,
               COALESCE(e.utility_score, 0.5) AS utility_score
        """
        records, _, _ = await driver.execute_query(query)
        golden = [dict(r) for r in records]

        # Build usage stats from query results
        usage_stats = {
            g["uuid"]: {
                "loaded_count": g["loaded_count"],
                "referenced_count": g["referenced_count"],
            }
            for g in golden
            if g.get("uuid")
        }

        return golden, usage_stats
    except Exception as e:
        logger.error("Failed to fetch mandates: %s", e)
        return [], {}


async def fetch_usage_stats(uuids: list[str]) -> dict[str, dict[str, int]]:
    """
    Fetch usage statistics for given UUIDs from Neo4j.

    Returns dict of {uuid: {loaded_count, referenced_count}}
    """
    if not uuids:
        return {}

    try:
        from .graphiti_client import get_graphiti

        graphiti = get_graphiti()
        driver = graphiti.driver

        query = """
        MATCH (e:Episodic)
        WHERE e.uuid IN $uuids
        RETURN e.uuid AS uuid,
               COALESCE(e.loaded_count, 0) AS loaded_count,
               COALESCE(e.referenced_count, 0) AS referenced_count
        """

        records, _, _ = await driver.execute_query(query, uuids=uuids)

        return {
            r["uuid"]: {
                "loaded_count": r["loaded_count"],
                "referenced_count": r["referenced_count"],
            }
            for r in records
        }
    except Exception as e:
        logger.warning("Failed to fetch usage stats: %s", e)
        return {}
