"""
Backup and restore strategies for Neo4j Graphiti database.
"""

import logging
from pathlib import Path

from neo4j import AsyncDriver

from .backup_io import convert_neo4j_datetimes, load_json, save_json

logger = logging.getLogger(__name__)

# Cypher queries
EPISODE_QUERY = """
MATCH (e:Episodic)
RETURN e.uuid AS uuid, e.name AS name, e.content AS content,
       e.source AS source, e.source_description AS source_description,
       e.created_at AS created_at, e.valid_at AS valid_at,
       e.group_id AS group_id, e.entity_edges AS entity_edges,
       e.injection_tier AS injection_tier,
       e.loaded_count AS loaded_count,
       e.referenced_count AS referenced_count,
       e.token_count AS token_count
"""

ENTITY_QUERY = """
MATCH (e:Entity)
RETURN e.uuid AS uuid, e.name AS name, e.summary AS summary,
       e.entity_type AS entity_type, e.created_at AS created_at,
       e.group_id AS group_id
"""

EDGE_QUERY = """
MATCH (e:EntityEdge)
RETURN e.uuid AS uuid, e.fact AS fact, e.episodes AS episodes,
       e.expired_at AS expired_at, e.valid_at AS valid_at,
       e.invalid_at AS invalid_at, e.created_at AS created_at,
       e.group_id AS group_id
"""


async def backup_episodes(driver: AsyncDriver, backup_path: Path) -> int:
    """Backup Episodic nodes to JSON."""
    logger.info("Backing up Episodic nodes...")
    records, _, _ = await driver.execute_query(EPISODE_QUERY)
    episodes = [
        convert_neo4j_datetimes(dict(r), ["created_at", "valid_at"])
        for r in records
    ]
    save_json(backup_path / "episodes.json", episodes)
    logger.info("Backed up %d episodes", len(episodes))
    return len(episodes)


async def backup_entities(driver: AsyncDriver, backup_path: Path) -> int:
    """Backup Entity nodes to JSON."""
    logger.info("Backing up Entity nodes...")
    records, _, _ = await driver.execute_query(ENTITY_QUERY)
    entities = [
        convert_neo4j_datetimes(dict(r), ["created_at"])
        for r in records
    ]
    save_json(backup_path / "entities.json", entities)
    logger.info("Backed up %d entities", len(entities))
    return len(entities)


async def backup_edges(driver: AsyncDriver, backup_path: Path) -> int:
    """Backup EntityEdge nodes to JSON."""
    logger.info("Backing up EntityEdge relationships...")
    records, _, _ = await driver.execute_query(EDGE_QUERY)
    edges = [
        convert_neo4j_datetimes(
            dict(r), ["created_at", "valid_at", "invalid_at", "expired_at"]
        )
        for r in records
    ]
    save_json(backup_path / "edges.json", edges)
    logger.info("Backed up %d edges", len(edges))
    return len(edges)


async def restore_episodes(driver: AsyncDriver, backup_path: Path) -> int:
    """Restore Episodic nodes from JSON."""
    logger.info("Restoring episodes...")
    episodes = load_json(backup_path / "episodes.json")

    query = """
    CREATE (e:Episodic {
        uuid: $uuid,
        name: $name,
        content: $content,
        source: $source,
        source_description: $source_description,
        created_at: datetime($created_at),
        valid_at: datetime($valid_at),
        group_id: $group_id,
        entity_edges: $entity_edges,
        injection_tier: $injection_tier,
        loaded_count: $loaded_count,
        referenced_count: $referenced_count,
        token_count: $token_count
    })
    """

    for ep in episodes:
        params = dict(ep)
        params.setdefault("injection_tier", "reference")
        params.setdefault("loaded_count", 0)
        params.setdefault("referenced_count", 0)
        params.setdefault("token_count", 0)
        await driver.execute_query(query, **params)

    logger.info("Restored %d episodes", len(episodes))
    return len(episodes)


async def restore_entities(driver: AsyncDriver, backup_path: Path) -> int:
    """Restore Entity nodes from JSON."""
    logger.info("Restoring entities...")
    entities = load_json(backup_path / "entities.json")

    query = """
    CREATE (e:Entity {
        uuid: $uuid,
        name: $name,
        summary: $summary,
        entity_type: $entity_type,
        created_at: datetime($created_at),
        group_id: $group_id
    })
    """

    for ent in entities:
        await driver.execute_query(query, **ent)

    logger.info("Restored %d entities", len(entities))
    return len(entities)


async def restore_edges(driver: AsyncDriver, backup_path: Path) -> int:
    """Restore EntityEdge nodes from JSON."""
    logger.info("Restoring edges...")
    edges = load_json(backup_path / "edges.json")

    query = """
    CREATE (e:EntityEdge {
        uuid: $uuid,
        fact: $fact,
        episodes: $episodes,
        expired_at: $expired_at,
        valid_at: datetime($valid_at),
        invalid_at: $invalid_at,
        created_at: datetime($created_at),
        group_id: $group_id
    })
    """

    for edge in edges:
        # Handle None datetime fields
        params = dict(edge)
        for field in ["expired_at", "invalid_at"]:
            if params.get(field) is None:
                params.pop(field, None)
        await driver.execute_query(query, **params)

    logger.info("Restored %d edges", len(edges))
    return len(edges)


async def delete_all_data(driver: AsyncDriver) -> None:
    """Delete all nodes and relationships from database."""
    logger.info("Deleting existing data...")
    await driver.execute_query("MATCH (n) DETACH DELETE n")
