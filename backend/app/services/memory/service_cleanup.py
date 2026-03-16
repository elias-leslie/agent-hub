"""Cleanup operations for memory service."""

from __future__ import annotations

import logging
from typing import Any

from .repository import get_memory_repository

logger = logging.getLogger(__name__)


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
