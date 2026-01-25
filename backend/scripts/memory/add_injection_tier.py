#!/usr/bin/env python3
"""
Migration script to add injection_tier field to all Episodic nodes.

Sets injection_tier='pending_review' for all episodes without a tier,
marking them for manual review during the tier unification task.

Usage:
    # Dry run - show what would be updated
    python -m scripts.memory.add_injection_tier --dry-run

    # Run migration
    python -m scripts.memory.add_injection_tier
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
    Run the injection_tier migration.

    Args:
        dry_run: If True, only report what would be done

    Returns:
        Dict with migration stats
    """
    graphiti = get_graphiti()
    driver = graphiti.driver

    count_query = """
    MATCH (e:Episodic)
    WHERE e.injection_tier IS NULL
    RETURN count(e) AS count
    """

    records, _, _ = await driver.execute_query(count_query)
    count = records[0]["count"] if records else 0

    logger.info("Found %d episodes without injection_tier", count)

    if dry_run:
        logger.info("DRY RUN - would update %d episodes", count)
        return {"dry_run": True, "would_update": count}

    if count == 0:
        logger.info("No episodes need updating")
        return {"updated": 0}

    update_query = """
    MATCH (e:Episodic)
    WHERE e.injection_tier IS NULL
    SET e.injection_tier = 'pending_review'
    RETURN count(e) AS updated
    """

    records, _, _ = await driver.execute_query(update_query)
    updated = records[0]["updated"] if records else 0

    logger.info("Updated %d episodes with injection_tier='pending_review'", updated)

    index_query = """
    CREATE INDEX episode_injection_tier IF NOT EXISTS
    FOR (e:Episodic)
    ON (e.injection_tier)
    """

    try:
        await driver.execute_query(index_query)
        logger.info("Created index on injection_tier")
    except Exception as e:
        logger.warning("Index creation failed (may already exist): %s", e)

    return {"updated": updated}


def main() -> None:
    parser = argparse.ArgumentParser(description="Add injection_tier to Episodic nodes")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    args = parser.parse_args()

    result = asyncio.run(run_migration(dry_run=args.dry_run))
    logger.info("Migration result: %s", result)


if __name__ == "__main__":
    main()
