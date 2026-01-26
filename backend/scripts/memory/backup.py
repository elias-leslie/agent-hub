#!/usr/bin/env python3
"""
Memory backup utility for Agent Hub Graphiti database.

Creates backups of Neo4j Graphiti data before destructive operations
like entity consolidation, legacy cleanup, or schema migrations.

Usage:
    python -m scripts.memory.backup --name "pre-consolidation"
    python -m scripts.memory.backup --list
    python -m scripts.memory.backup --restore <backup_id>
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

# Add backend to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.memory.graphiti_client import get_graphiti

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Backup directory
BACKUP_DIR = Path(__file__).parent.parent.parent.parent / "backups" / "memory"


async def create_backup(name: str) -> str:
    """
    Create a backup of the Graphiti database.

    Exports all nodes and relationships to JSON files.

    Args:
        name: Descriptive name for the backup

    Returns:
        Backup ID (timestamp-based)
    """
    # Create backup ID
    backup_id = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    backup_name = f"{backup_id}_{name}"
    backup_path = BACKUP_DIR / backup_name
    backup_path.mkdir(parents=True, exist_ok=True)

    logger.info("Creating backup: %s", backup_name)

    graphiti = get_graphiti()
    driver = graphiti.driver

    # Backup episodes
    logger.info("Backing up Episodic nodes...")
    episode_query = """
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
    episode_records, _, _ = await driver.execute_query(episode_query)
    episodes = []
    for record in episode_records:
        episode = dict(record)
        # Convert neo4j datetime to ISO string
        if episode.get("created_at") and hasattr(episode["created_at"], "to_native"):
            episode["created_at"] = episode["created_at"].to_native().isoformat()
        if episode.get("valid_at") and hasattr(episode["valid_at"], "to_native"):
            episode["valid_at"] = episode["valid_at"].to_native().isoformat()
        episodes.append(episode)

    with open(backup_path / "episodes.json", "w") as f:
        json.dump(episodes, f, indent=2)
    logger.info("Backed up %d episodes", len(episodes))

    # Backup entities
    logger.info("Backing up Entity nodes...")
    entity_query = """
    MATCH (e:Entity)
    RETURN e.uuid AS uuid, e.name AS name, e.summary AS summary,
           e.entity_type AS entity_type, e.created_at AS created_at,
           e.group_id AS group_id
    """
    entity_records, _, _ = await driver.execute_query(entity_query)
    entities = []
    for record in entity_records:
        entity = dict(record)
        if entity.get("created_at") and hasattr(entity["created_at"], "to_native"):
            entity["created_at"] = entity["created_at"].to_native().isoformat()
        entities.append(entity)

    with open(backup_path / "entities.json", "w") as f:
        json.dump(entities, f, indent=2)
    logger.info("Backed up %d entities", len(entities))

    # Backup edges
    logger.info("Backing up EntityEdge relationships...")
    edge_query = """
    MATCH (e:EntityEdge)
    RETURN e.uuid AS uuid, e.fact AS fact, e.episodes AS episodes,
           e.expired_at AS expired_at, e.valid_at AS valid_at,
           e.invalid_at AS invalid_at, e.created_at AS created_at,
           e.group_id AS group_id
    """
    edge_records, _, _ = await driver.execute_query(edge_query)
    edges = []
    for record in edge_records:
        edge = dict(record)
        # Convert datetime fields
        for field in ["created_at", "valid_at", "invalid_at", "expired_at"]:
            if edge.get(field) and hasattr(edge[field], "to_native"):
                edge[field] = edge[field].to_native().isoformat()
        edges.append(edge)

    with open(backup_path / "edges.json", "w") as f:
        json.dump(edges, f, indent=2)
    logger.info("Backed up %d edges", len(edges))

    # Save backup metadata
    metadata = {
        "backup_id": backup_id,
        "name": name,
        "created_at": datetime.now(UTC).isoformat(),
        "episode_count": len(episodes),
        "entity_count": len(entities),
        "edge_count": len(edges),
    }
    with open(backup_path / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)

    logger.info("Backup complete: %s", backup_path)
    logger.info(
        "Backup stats: %d episodes, %d entities, %d edges",
        len(episodes),
        len(entities),
        len(edges),
    )

    await graphiti.close()
    return backup_id


async def list_backups() -> list[dict]:
    """
    List all available backups.

    Returns:
        List of backup metadata dicts
    """
    if not BACKUP_DIR.exists():
        return []

    backups = []
    for backup_path in sorted(BACKUP_DIR.iterdir(), reverse=True):
        if not backup_path.is_dir():
            continue

        metadata_path = backup_path / "metadata.json"
        if metadata_path.exists():
            with open(metadata_path) as f:
                metadata = json.load(f)
            backups.append(metadata)

    return backups


async def restore_backup(backup_id: str) -> None:
    """
    Restore from a backup.

    WARNING: This will DELETE all existing data and replace with backup.

    Args:
        backup_id: ID of the backup to restore
    """
    # Find backup
    backup_dirs = list(BACKUP_DIR.glob(f"{backup_id}_*"))
    if not backup_dirs:
        logger.error("Backup not found: %s", backup_id)
        sys.exit(1)

    backup_path = backup_dirs[0]
    logger.warning("Restoring from backup: %s", backup_path.name)
    logger.warning("This will DELETE all existing data!")

    # Confirm
    confirm = input("Type 'DELETE ALL DATA' to confirm: ")
    if confirm != "DELETE ALL DATA":
        logger.info("Restore cancelled")
        return

    graphiti = get_graphiti()
    driver = graphiti.driver

    # Delete all existing data
    logger.info("Deleting existing data...")
    await driver.execute_query("MATCH (n) DETACH DELETE n")

    # Restore episodes
    logger.info("Restoring episodes...")
    with open(backup_path / "episodes.json") as f:
        episodes = json.load(f)

    for ep in episodes:
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
        params = dict(ep)
        params.setdefault("injection_tier", "reference")
        params.setdefault("loaded_count", 0)
        params.setdefault("referenced_count", 0)
        params.setdefault("token_count", 0)
        await driver.execute_query(query, **params)

    logger.info("Restored %d episodes", len(episodes))

    # Restore entities
    logger.info("Restoring entities...")
    with open(backup_path / "entities.json") as f:
        entities = json.load(f)

    for ent in entities:
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
        await driver.execute_query(query, **ent)

    logger.info("Restored %d entities", len(entities))

    # Restore edges
    logger.info("Restoring edges...")
    with open(backup_path / "edges.json") as f:
        edges = json.load(f)

    for edge in edges:
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
        # Handle None datetime fields
        params = dict(edge)
        for field in ["expired_at", "invalid_at"]:
            if params.get(field) is None:
                params.pop(field, None)

        await driver.execute_query(query, **params)

    logger.info("Restored %d edges", len(edges))
    logger.info("Restore complete!")

    await graphiti.close()


async def main():
    parser = argparse.ArgumentParser(description="Memory backup utility")
    parser.add_argument("--name", help="Create backup with this name")
    parser.add_argument("--list", action="store_true", help="List backups")
    parser.add_argument("--restore", help="Restore from backup ID")

    args = parser.parse_args()

    if args.list:
        backups = await list_backups()
        if not backups:
            print("No backups found")
            return

        print("Available backups:")
        for backup in backups:
            print(f"\nID: {backup['backup_id']}")
            print(f"Name: {backup['name']}")
            print(f"Created: {backup['created_at']}")
            print(
                f"Data: {backup['episode_count']} episodes, "
                f"{backup['entity_count']} entities, "
                f"{backup['edge_count']} edges"
            )

    elif args.restore:
        await restore_backup(args.restore)

    elif args.name:
        backup_id = await create_backup(args.name)
        print(f"Backup created: {backup_id}")

    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
