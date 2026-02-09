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
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

# Add backend to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from neo4j import AsyncDriver

from app.services.memory.graphiti_client import get_graphiti

from .backup_io import ensure_backup_dir, load_json, save_json
from .backup_strategies import (
    backup_edges,
    backup_entities,
    backup_episodes,
    delete_all_data,
    restore_edges,
    restore_entities,
    restore_episodes,
)

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

    Args:
        name: Descriptive name for the backup

    Returns:
        Backup ID (timestamp-based)
    """
    backup_id = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    backup_name = f"{backup_id}_{name}"
    backup_path = ensure_backup_dir(BACKUP_DIR, backup_name)

    logger.info("Creating backup: %s", backup_name)

    graphiti = get_graphiti()
    driver = cast(AsyncDriver, graphiti.driver)

    # Backup all data
    episode_count = await backup_episodes(driver, backup_path)
    entity_count = await backup_entities(driver, backup_path)
    edge_count = await backup_edges(driver, backup_path)

    # Save metadata
    metadata = {
        "backup_id": backup_id,
        "name": name,
        "created_at": datetime.now(UTC).isoformat(),
        "episode_count": episode_count,
        "entity_count": entity_count,
        "edge_count": edge_count,
    }
    save_json(backup_path / "metadata.json", metadata)

    logger.info("Backup complete: %s", backup_path)
    logger.info(
        "Backup stats: %d episodes, %d entities, %d edges",
        episode_count,
        entity_count,
        edge_count,
    )

    await graphiti.close()  # type: ignore[no-untyped-call]
    return backup_id


async def list_backups() -> list[dict[str, Any]]:
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
            metadata = load_json(metadata_path)
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
    driver = cast(AsyncDriver, graphiti.driver)

    # Delete and restore
    await delete_all_data(driver)
    await restore_episodes(driver, backup_path)
    await restore_entities(driver, backup_path)
    await restore_edges(driver, backup_path)

    logger.info("Restore complete!")
    await graphiti.close()  # type: ignore[no-untyped-call]


async def main() -> None:
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
