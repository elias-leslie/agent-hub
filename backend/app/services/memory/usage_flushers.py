"""
Database flush operations for usage tracking.

Handles flushing buffered usage metrics to Neo4j (counters) and PostgreSQL
(historical logs).
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import insert

from app.db import _get_session_factory
from app.models import UsageStatLog

from .graphiti_client import get_graphiti

logger = logging.getLogger(__name__)

# Metric types
METRIC_LOADED = "loaded"
METRIC_REFERENCED = "referenced"
METRIC_SUCCESS = "success"
METRIC_HELPFUL = "helpful"
METRIC_HARMFUL = "harmful"


async def flush_to_neo4j(counters: dict[str, dict[str, int]]) -> None:
    """
    Update counter properties on Neo4j Episodic nodes.

    Batch updates usage counters and computes utility_score:
    - If agent ratings exist: helpful_count / (helpful_count + harmful_count)
    - Otherwise: referenced_count / loaded_count

    Args:
        counters: Dictionary of {episode_uuid: {metric_type: count}}
    """
    graphiti = get_graphiti()
    driver = graphiti.driver

    # Batch update query with utility_score computation
    # Note: UUID can be Episodic node, Entity node, or EntityEdge (relationship)
    # Search returns EntityEdge UUIDs - find Episodic via Entity nodes the edge connects
    query = """
    UNWIND $updates AS update
    OPTIONAL MATCH (episodic:Episodic {uuid: update.uuid})
    OPTIONAL MATCH (source1:Episodic)-[:MENTIONS]->(entity:Entity {uuid: update.uuid})
    OPTIONAL MATCH (e1:Entity)-[edge:RELATES_TO {uuid: update.uuid}]->(e2:Entity)
    OPTIONAL MATCH (source2:Episodic)-[:MENTIONS]->(e1)
    WITH update, COALESCE(episodic, source1, source2) AS e
    WHERE e IS NOT NULL
    SET e.loaded_count = COALESCE(e.loaded_count, 0) + update.loaded,
        e.referenced_count = COALESCE(e.referenced_count, 0) + update.referenced,
        e.success_count = COALESCE(e.success_count, 0) + update.success,
        e.helpful_count = COALESCE(e.helpful_count, 0) + update.helpful,
        e.harmful_count = COALESCE(e.harmful_count, 0) + update.harmful,
        e.last_used_at = datetime($now)
    WITH e
    SET e.utility_score = CASE
        WHEN (COALESCE(e.helpful_count, 0) + COALESCE(e.harmful_count, 0)) > 0
        THEN toFloat(COALESCE(e.helpful_count, 0)) /
             toFloat(COALESCE(e.helpful_count, 0) + COALESCE(e.harmful_count, 0))
        WHEN COALESCE(e.loaded_count, 0) > 0
        THEN toFloat(COALESCE(e.referenced_count, 0)) / toFloat(e.loaded_count)
        ELSE 0.0
    END
    RETURN count(e) AS updated
    """

    updates = [
        {
            "uuid": uuid,
            "loaded": metrics.get(METRIC_LOADED, 0),
            "referenced": metrics.get(METRIC_REFERENCED, 0),
            "success": metrics.get(METRIC_SUCCESS, 0),
            "helpful": metrics.get(METRIC_HELPFUL, 0),
            "harmful": metrics.get(METRIC_HARMFUL, 0),
        }
        for uuid, metrics in counters.items()
    ]

    now = datetime.now(UTC).isoformat()

    records, _, _ = await driver.execute_query(query, updates=updates, now=now)

    updated_count = records[0]["updated"] if records else 0
    logger.info("Updated %d Neo4j episode nodes", updated_count)


async def flush_to_postgres(counters: dict[str, dict[str, int]]) -> None:
    """
    Insert historical usage logs to PostgreSQL.

    Creates individual log records for each metric increment.

    Args:
        counters: Dictionary of {episode_uuid: {metric_type: count}}
    """
    session_factory = _get_session_factory()

    # Build insert values
    rows = []
    now = datetime.now(UTC)
    for uuid, metrics in counters.items():
        for metric_type, value in metrics.items():
            if value > 0:
                rows.append(
                    {
                        "episode_uuid": uuid,
                        "metric_type": metric_type,
                        "value": value,
                        "timestamp": now,
                    }
                )

    if not rows:
        return

    async with session_factory() as session:
        # Use bulk insert for efficiency
        stmt = insert(UsageStatLog).values(rows)
        await session.execute(stmt)
        await session.commit()

    logger.info("Inserted %d usage stat logs to PostgreSQL", len(rows))


async def init_usage_properties() -> int:
    """
    Initialize usage properties on existing Episodic nodes.

    Sets default values for loaded_count, referenced_count, success_count,
    helpful_count, harmful_count, and utility_score on nodes that don't have them.

    Returns the number of nodes updated.
    """
    graphiti = get_graphiti()
    driver = graphiti.driver

    query = """
    MATCH (e:Episodic)
    WHERE e.loaded_count IS NULL
       OR e.referenced_count IS NULL
       OR e.success_count IS NULL
       OR e.helpful_count IS NULL
       OR e.harmful_count IS NULL
       OR e.utility_score IS NULL
    SET e.loaded_count = COALESCE(e.loaded_count, 0),
        e.referenced_count = COALESCE(e.referenced_count, 0),
        e.success_count = COALESCE(e.success_count, 0),
        e.helpful_count = COALESCE(e.helpful_count, 0),
        e.harmful_count = COALESCE(e.harmful_count, 0),
        e.utility_score = COALESCE(e.utility_score, 0.0)
    RETURN count(e) AS updated
    """

    records, _, _ = await driver.execute_query(query)
    updated = records[0]["updated"] if records else 0

    logger.info("Initialized usage properties on %d Episodic nodes", updated)
    return updated
