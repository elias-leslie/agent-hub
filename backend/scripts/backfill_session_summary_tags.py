#!/usr/bin/env python3
"""Backfill is_session_summary=true on existing session summary episodes.

Scans Neo4j for Episodic nodes whose content starts with '[Session Summary:'
and sets is_session_summary=true. This prevents session summaries from
polluting the reference index (REF_IDX) during context injection.

Usage:
    cd backend && .venv/bin/python scripts/backfill_session_summary_tags.py [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


async def backfill_session_summary_tags(dry_run: bool = False) -> int:
    """Tag existing session summary episodes with is_session_summary=true.

    Returns:
        Number of episodes updated.
    """
    from app.services.memory.graphiti_client import get_graphiti

    graphiti = get_graphiti()
    driver = graphiti.driver

    # Find all episodes that look like session summaries
    find_query = """
    MATCH (e:Episodic)
    WHERE e.content STARTS WITH '[Session Summary:'
      AND COALESCE(e.is_session_summary, false) = false
    RETURN e.uuid AS uuid, left(e.content, 80) AS preview
    """

    records, _, _ = await driver.execute_query(find_query)
    episodes = [dict(r) for r in records]

    if not episodes:
        logger.info("No untagged session summary episodes found")
        return 0

    logger.info("Found %d untagged session summary episodes", len(episodes))

    if dry_run:
        for ep in episodes:
            logger.info("  Would tag: %s - %s", ep["uuid"], ep["preview"])
        logger.info("Dry run: no changes made")
        return len(episodes)

    # Batch update
    update_query = """
    MATCH (e:Episodic)
    WHERE e.content STARTS WITH '[Session Summary:'
      AND COALESCE(e.is_session_summary, false) = false
    SET e.is_session_summary = true
    RETURN count(e) AS updated
    """

    result, _, _ = await driver.execute_query(update_query)
    updated = result[0]["updated"] if result else 0

    logger.info("Tagged %d session summary episodes with is_session_summary=true", updated)
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill session summary tags")
    parser.add_argument("--dry-run", action="store_true", help="Preview without making changes")
    args = parser.parse_args()

    count = asyncio.run(backfill_session_summary_tags(dry_run=args.dry_run))
    logger.info("Done. %d episodes %s.", count, "would be updated" if args.dry_run else "updated")


if __name__ == "__main__":
    main()
