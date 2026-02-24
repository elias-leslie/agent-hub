"""
TTL-based memory cleanup operations.

Handles cleanup of memories that haven't been accessed within TTL period.
Uses MemoryRepository.cleanup_stale() for PostgreSQL-based cleanup.
"""

import logging
from typing import Any

from .repository import get_memory_repository

logger = logging.getLogger(__name__)


async def cleanup_stale_memories(
    driver: Any = None,
    group_id: str = "",
    ttl_days: int = 30,
) -> dict[str, Any]:
    """
    Clean up memories that haven't been accessed within TTL period.

    Delegates to MemoryRepository.cleanup_stale() which implements the
    system activity safeguard: if the system itself hasn't been active for
    30+ days, cleanup is skipped to prevent accidental mass deletion.

    Args:
        driver: Ignored (kept for backward-compat signature).
        group_id: Group ID to clean up.
        ttl_days: Days without access before memory is considered stale.

    Returns:
        Dict with cleanup results: deleted count, skipped, and reason.
    """
    try:
        repo = get_memory_repository()
        result = await repo.cleanup_stale(
            group_id=group_id or None,
            ttl_days=ttl_days,
        )
        deleted = result.get("deleted", 0)
        if deleted:
            logger.info(
                "Cleanup complete for group %s: %d stale memories deleted",
                group_id,
                deleted,
            )
        return result

    except Exception as e:
        logger.error("Cleanup failed: %s", e)
        return {"deleted": 0, "skipped": True, "reason": f"Cleanup failed: {e}"}
