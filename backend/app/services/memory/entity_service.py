"""Entity browser service for auditing Graphiti-extracted entities."""

from __future__ import annotations

import logging
from typing import Any

from .query_builders import convert_neo4j_datetime

logger = logging.getLogger(__name__)


async def list_entities(
    driver: Any,
    group_id: str,
    search: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> dict[str, Any]:
    search_clause = ""
    params: dict[str, Any] = {"group_id": group_id, "limit": limit, "offset": offset}

    if search:
        search_clause = "AND toLower(e.name) CONTAINS toLower($search)"
        params["search"] = search

    query = f"""
        MATCH (e:Entity {{group_id: $group_id}})
        WHERE true {search_clause}
        WITH e
        ORDER BY e.name
        WITH collect(e) AS all_entities, count(e) AS total
        UNWIND all_entities[$offset..$offset + $limit] AS e
        OPTIONAL MATCH (ep:Episodic)-[:MENTIONS]->(e)
        OPTIONAL MATCH (e)-[:RELATES_TO]-(other:Entity)
        RETURN
            e.name AS name,
            e.uuid AS uuid,
            e.group_id AS group_id,
            e.created_at AS created_at,
            e.summary AS summary,
            count(DISTINCT ep) AS episode_count,
            count(DISTINCT other) AS edge_count,
            total
        ORDER BY episode_count DESC
    """

    try:
        records, _, _ = await driver.execute_query(query, **params)
        total = records[0]["total"] if records else 0

        entities = [
            {
                "name": r["name"],
                "uuid": r["uuid"],
                "group_id": r["group_id"],
                "created_at": convert_neo4j_datetime(r["created_at"]),
                "summary": r["summary"],
                "episode_count": r["episode_count"],
                "edge_count": r["edge_count"],
            }
            for r in records
        ]
        return {"entities": entities, "total": total}
    except Exception:
        logger.exception("Failed to list entities for group_id=%s", group_id)
        raise


async def get_entity_episodes(
    driver: Any,
    entity_name: str,
    group_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    query = """
        MATCH (ep:Episodic)-[:MENTIONS]->(e:Entity {name: $name, group_id: $group_id})
        RETURN
            ep.uuid AS uuid,
            left(ep.content, 300) AS content,
            ep.injection_tier AS injection_tier,
            ep.created_at AS created_at
        ORDER BY ep.created_at DESC
        LIMIT $limit
    """

    try:
        records, _, _ = await driver.execute_query(
            query, name=entity_name, group_id=group_id, limit=limit
        )
        return [
            {
                "uuid": r["uuid"],
                "content": r["content"],
                "injection_tier": r["injection_tier"],
                "created_at": convert_neo4j_datetime(r["created_at"]),
            }
            for r in records
        ]
    except Exception:
        logger.exception("Failed to get episodes for entity=%s", entity_name)
        raise


async def get_entity_health(
    driver: Any,
    group_id: str,
) -> dict[str, Any]:
    query = """
        MATCH (e:Entity {group_id: $group_id})
        WITH count(e) AS total_entities

        OPTIONAL MATCH (orphan:Entity {group_id: $group_id})
        WHERE NOT EXISTS { MATCH (:Episodic)-[:MENTIONS]->(orphan) }
        WITH total_entities, count(orphan) AS orphan_count

        OPTIONAL MATCH (dup:Entity {group_id: $group_id})
        WITH total_entities, orphan_count, dup.name AS dup_name, count(dup) AS name_count
        WHERE name_count > 1
        WITH total_entities, orphan_count,
             count(dup_name) AS duplicate_count,
             collect(dup_name)[..20] AS duplicate_names

        OPTIONAL MATCH ()-[r:RELATES_TO]->()
        WHERE r.group_id = $group_id
        WITH total_entities, orphan_count, duplicate_count, duplicate_names,
             count(r) AS total_edges

        RETURN
            total_entities,
            orphan_count,
            duplicate_count,
            duplicate_names,
            total_edges
    """

    try:
        records, _, _ = await driver.execute_query(query, group_id=group_id)
        if not records:
            return {
                "total_entities": 0,
                "orphan_count": 0,
                "duplicate_count": 0,
                "duplicate_names": [],
                "total_edges": 0,
            }

        r = records[0]
        return {
            "total_entities": r["total_entities"],
            "orphan_count": r["orphan_count"],
            "duplicate_count": r["duplicate_count"],
            "duplicate_names": r["duplicate_names"],
            "total_edges": r["total_edges"],
        }
    except Exception:
        logger.exception("Failed to get entity health for group_id=%s", group_id)
        raise
