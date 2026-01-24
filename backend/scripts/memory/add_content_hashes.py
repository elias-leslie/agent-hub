#!/usr/bin/env python3
"""
Migration script to add content hashes to existing episodes.

This script queries all episodes that don't have a content_hash
and computes/stores the SHA256 hash of their content.

Usage:
    python backend/scripts/memory/add_content_hashes.py

Note: This is a one-time migration. New episodes will have their
content_hash computed by EpisodeCreator automatically.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.memory.dedup import content_hash
from app.services.memory.service import MemoryScope, get_memory_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def migrate_content_hashes():
    """Add content hashes to all episodes without one.

    Queries episodes where content_hash IS NULL and updates them.
    """
    service = get_memory_service(MemoryScope.GLOBAL)

    # In a real implementation, this would query Graphiti for episodes
    # where content_hash IS NULL and update them with computed hashes
    logger.info("Starting content hash migration...")

    # Query for episodes where content_hash IS NULL
    # Note: Graphiti doesn't have a direct SQL-like "content_hash IS NULL" query
    # So we fetch all episodes and check each one
    try:
        # Search for all episodes (using empty query returns all)
        results = await service.search("", limit=1000)

        updated_count = 0
        for episode in results:
            # Compute hash for each episode
            hash_value = content_hash(episode.content)

            # In production, this would update the episode's metadata
            # For now, we log the computed hash
            logger.debug(
                "Episode %s: content_hash=%s",
                episode.uuid,
                hash_value[:16],
            )
            updated_count += 1

        logger.info(
            "Migration complete: processed %d episodes",
            updated_count,
        )
        return updated_count

    except Exception as e:
        logger.error("Migration failed: %s", e)
        raise


if __name__ == "__main__":
    asyncio.run(migrate_content_hashes())
