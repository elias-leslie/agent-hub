#!/usr/bin/env python3
"""
Fix mandate episodes that have BOTH old format (type:MANDATE tier:ALWAYS)
AND new marker (golden_standard).

Replaces the source_description with the clean new format:
  {category} tier:mandate source:golden_standard confidence:100

Usage:
    # Dry run - show what would be updated
    python -m scripts.memory.fix_mandate_format --dry-run

    # Run fix
    python -m scripts.memory.fix_mandate_format
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.memory.graphiti_client import get_graphiti

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def extract_category(old_desc: str) -> str:
    """Extract category from old source_description format.

    Format: coding_standard type:MANDATE tier:ALWAYS source:golden_standard
    Category is the first word before any tag (type:, tier:, source:, etc.)
    """
    parts = old_desc.split()
    if parts:
        return parts[0]
    return "coding_standard"


def clean_source_description(old_desc: str) -> str:
    """Convert old format to clean new format.

    Old: coding_standard type:MANDATE tier:ALWAYS source:golden_standard
    New: coding_standard tier:mandate source:golden_standard confidence:100
    """
    category = extract_category(old_desc)
    return f"{category} tier:mandate source:golden_standard confidence:100"


async def run_fix(dry_run: bool = False) -> dict:
    """
    Fix mandate episodes with mixed old/new format.

    Args:
        dry_run: If True, only report what would be done

    Returns:
        Dict with fix stats
    """
    graphiti = get_graphiti()
    driver = graphiti.driver

    find_query = """
    MATCH (e:Episodic)
    WHERE (e.source_description CONTAINS 'type:MANDATE' OR e.source_description CONTAINS 'tier:ALWAYS')
      AND e.source_description CONTAINS 'golden_standard'
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
        logger.info("No episodes found needing fix")
        await graphiti.close()
        return {"found": 0, "updated": 0, "skipped": 0}

    logger.info("Found %d episodes needing format fix", len(episodes))

    if dry_run:
        logger.info("DRY RUN - Would update the following episodes:")
        for ep in episodes:
            old = ep["source_description"]
            new = clean_source_description(old)
            logger.info("  [%s] %s", ep["uuid"][:8], ep["name"])
            logger.info("    OLD: %s", old)
            logger.info("    NEW: %s", new)
        await graphiti.close()
        return {"found": len(episodes), "updated": 0, "skipped": 0}

    updated = 0
    skipped = 0

    for ep in episodes:
        new_source_description = clean_source_description(ep["source_description"])
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
                logger.info("Fixed [%s] %s", ep["uuid"][:8], ep["name"])
            else:
                skipped += 1
                logger.warning("Skipped [%s] %s", ep["uuid"][:8], ep["name"])
        except Exception as e:
            logger.error("Failed to fix episode %s: %s", ep["uuid"][:8], e)
            skipped += 1

    await graphiti.close()
    logger.info("Fix complete: %d updated, %d skipped", updated, skipped)
    return {"found": len(episodes), "updated": updated, "skipped": skipped}


async def main():
    parser = argparse.ArgumentParser(
        description="Fix mandate episodes to use clean source_description format"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be updated without making changes",
    )

    args = parser.parse_args()

    result = await run_fix(dry_run=args.dry_run)

    if args.dry_run:
        print(f"\nWould fix {result['found']} episodes")
    else:
        print(f"\nFix complete: {result['updated']} updated, {result['skipped']} skipped")


if __name__ == "__main__":
    asyncio.run(main())
