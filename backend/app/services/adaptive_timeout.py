"""Redis-backed adaptive timeout service.

Stores computed per-model timeouts in Redis, derived from observed latency percentiles.
Falls back to catalog defaults when Redis data is unavailable.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_REDIS_KEY_PREFIX = "agent-hub:adaptive-timeout"
_TTL_SECONDS = 3600  # 1 hour


async def get_adaptive_timeout(model_id: str) -> float | None:
    """Check Redis for an adaptive timeout for the given model.

    Returns:
        Timeout in seconds, or None if no adaptive value is cached.
    """
    try:
        from app.db import get_redis

        redis = get_redis()
        value = await redis.get(f"{_REDIS_KEY_PREFIX}:{model_id}")
        if value is not None:
            return float(value)
    except Exception:
        logger.debug("Failed to read adaptive timeout from Redis for %s", model_id)
    return None


async def update_adaptive_timeouts(stats: list[dict[str, Any]]) -> int:
    """Bulk-write computed adaptive timeouts to Redis.

    Args:
        stats: List of dicts with 'model', 'p95_ms', and optionally 'catalog_floor'.

    Returns:
        Number of keys written.
    """
    from app.constants.catalog import MODEL_CATALOG_BY_ID

    try:
        from app.db import get_redis

        redis = get_redis()
    except Exception:
        logger.warning("Failed to get Redis for adaptive timeout update")
        return 0

    count = 0
    for s in stats:
        model_id = s["model"]
        entry = MODEL_CATALOG_BY_ID.get(model_id)
        catalog_floor = entry.timeout_hint_seconds if entry else 60.0
        adaptive = max(catalog_floor, min(s["p95_ms"] / 1000 * 1.5, 600.0))

        try:
            await redis.set(
                f"{_REDIS_KEY_PREFIX}:{model_id}",
                str(round(adaptive, 1)),
                ex=_TTL_SECONDS,
            )
            count += 1
        except Exception:
            logger.debug("Failed to write adaptive timeout for %s", model_id)

    logger.info("Updated %d adaptive timeouts in Redis", count)
    return count
