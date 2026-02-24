"""Cleanup operations for memory service.

Edge/entity cleanup operations are no-ops since PostgreSQL doesn't use
separate edge/entity nodes.
"""

from __future__ import annotations

import logging
from typing import Any

from .repository import get_memory_repository

logger = logging.getLogger(__name__)


async def cleanup_orphaned(group_id: str) -> dict[str, Any]:
    """
    Run orphaned cleanup operations.

    In PostgreSQL, there are no separate edge/entity graph nodes to become
    orphaned. This is effectively a no-op but returns compatible structure.

    Args:
        group_id: Group ID for filtering

    Returns:
        Combined results (all zeros since graph cleanup is N/A in PostgreSQL)
    """
    logger.debug("Orphaned cleanup called for group %s (no-op in PostgreSQL)", group_id)
    return {
        "edges_updated": 0,
        "edges_deleted": 0,
        "stale_refs_removed": 0,
        "entities_deleted": 0,
        "duplicates_merged": 0,
    }


async def cleanup_stale(group_id: str, ttl_days: int) -> dict[str, Any]:
    """
    Clean up memories that haven't been accessed within TTL period.

    Args:
        group_id: Group ID for filtering
        ttl_days: Days without access before memory is considered stale

    Returns:
        Dict with cleanup results: deleted count, skipped, and reason
    """
    repo = get_memory_repository()
    return await repo.cleanup_stale(group_id=group_id, ttl_days=ttl_days)
