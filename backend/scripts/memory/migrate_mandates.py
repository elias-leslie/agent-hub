#!/usr/bin/env python3
"""
Migration script to add golden_standard marker to old-format mandate episodes.

Finds episodes with 'type:MANDATE tier:ALWAYS' source_description format
and appends 'source:golden_standard' to make them appear in golden standards queries.

Usage:
    # Dry run - show what would be updated
    python -m scripts.memory.migrate_mandates --dry-run

    # Run migration
    python -m scripts.memory.migrate_mandates
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.memory.graphiti_client import get_graphiti

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def run_migration(dry_run: bool = False) -> dict:
    """
    Run the mandate episode migration.

    Args:
        dry_run: If True, only report what would be done

    Returns:
        Dict with migration stats
    """
    graphiti = get_graphiti()
    driver = graphiti.driver

    find_query = """
    MATCH (e:Episodic)
    WHERE (e.source_description CONTAINS 'type:MANDATE' OR e.source_description CONTAINS 'tier:ALWAYS')
      AND NOT e.source_description CONTAINS 'golden_standard'
    RETURN e.uuid AS uuid, e.name AS name, e.source_description AS source_description
    ORDER BY e.created_at
    """

    records, _, _ = await driver.execute_query(find_query)

    episodes = [
        {
            "uuid": r["uuid"],
            "name": r["name"],
            "source_description": r["source_description"],
        }
        for r in records
    ]

    if not episodes:
        logger.info("No episodes found needing migration")
        await graphiti.close()
        return {"found": 0, "updated": 0, "skipped": 0}

    logger.info("Found %d episodes needing migration", len(episodes))

    if dry_run:
        logger.info("DRY RUN - Would update the following episodes:")
        for ep in episodes:
            logger.info("  %s: %s", ep["uuid"][:8], ep["name"])
        await graphiti.close()
        return {"found": len(episodes), "updated": 0, "skipped": 0}

    updated = 0
    skipped = 0

    for ep in episodes:
        new_source_description = f"{ep['source_description']} source:golden_standard"
        update_query = """
        MATCH (e:Episodic {uuid: $uuid})
        SET e.source_description = $new_source_description
        RETURN e.uuid AS uuid
        """

        try:
            result, _, _ = await driver.execute_query(
                update_query,
                uuid=ep["uuid"],
                new_source_description=new_source_description,
            )
            if result:
                updated += 1
                logger.info("Updated %s: %s", ep["uuid"][:8], ep["name"])
            else:
                skipped += 1
                logger.warning("Skipped %s: %s", ep["uuid"][:8], ep["name"])
        except Exception as e:
            logger.error("Failed to migrate episode %s: %s", ep["uuid"][:8], e)
            skipped += 1

    await graphiti.close()
    logger.info("Migration complete: %d updated, %d skipped", updated, skipped)
    return {"found": len(episodes), "updated": updated, "skipped": skipped}


async def main():
    parser = argparse.ArgumentParser(
        description="Migrate mandate episodes to include golden_standard marker"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be updated without making changes",
    )

    args = parser.parse_args()

    result = await run_migration(dry_run=args.dry_run)

    if args.dry_run:
        print(f"\nWould update {result['found']} episodes")
    else:
        print(f"\nMigration complete: {result['updated']} updated, {result['skipped']} skipped")


if __name__ == "__main__":
    asyncio.run(main())
