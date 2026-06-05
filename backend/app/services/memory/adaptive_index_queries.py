"""
PostgreSQL query operations for adaptive index.

Handles fetching mandate data and usage statistics using MemoryRepository.
"""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .repository import MemoryRepository, get_memory_repository

logger = logging.getLogger(__name__)


async def fetch_mandates_with_stats(
    db: AsyncSession | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, int]]]:
    """
    Fetch mandates and their usage stats from PostgreSQL.

    Returns:
        Tuple of (golden_standards, usage_stats)
        - golden_standards: List of mandate dicts
        - usage_stats: Dict of {uuid: {loaded_count, referenced_count}}
    """
    try:
        repo = get_memory_repository()
        memories = await repo.list_by_scope_and_tier(
            tier="mandate",
            group_id="global",
            status="active",
            db=db,
        )
        golden = [MemoryRepository._to_dict(m) for m in memories]

        # Build usage stats from query results
        usage_stats = {
            g["uuid"]: {
                "loaded_count": g["loaded_count"],
                "referenced_count": g["referenced_count"],
            }
            for g in golden
            if g.get("uuid")
        }

        return golden, usage_stats
    except Exception as e:
        logger.error("Failed to fetch mandates: %s", e)
        return [], {}


async def fetch_usage_stats(uuids: list[str]) -> dict[str, dict[str, int]]:
    """
    Fetch usage statistics for given UUIDs from PostgreSQL.

    Returns dict of {uuid: {loaded_count, referenced_count}}
    """
    if not uuids:
        return {}

    try:
        repo = get_memory_repository()
        batch = await repo.batch_get(uuids)

        return {
            uid: {
                "loaded_count": data.get("loaded_count", 0),
                "referenced_count": data.get("referenced_count", 0),
            }
            for uid, data in batch.items()
        }
    except Exception as e:
        logger.warning("Failed to fetch usage stats: %s", e)
        return {}
