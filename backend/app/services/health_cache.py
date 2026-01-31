"""
Health check caching with async background refresh.

Implements the moltbot pattern:
- Cache health results for HEALTH_CACHE_TTL_SECONDS (default 60s)
- Return cached response immediately if valid
- Trigger background refresh on every request (deduped via lock)
- Concurrent requests share the same refresh promise
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Cache TTL in seconds (default 60s matches moltbot)
HEALTH_CACHE_TTL_SECONDS = int(os.environ.get("HEALTH_CACHE_TTL_SECONDS", "60"))


@dataclass
class CacheEntry[T]:
    """A cached health snapshot."""

    data: T
    timestamp: float
    version: int = 0

    @property
    def age_seconds(self) -> float:
        """Age of this cache entry in seconds."""
        return time.time() - self.timestamp

    @property
    def is_fresh(self) -> bool:
        """Whether this entry is within TTL."""
        return self.age_seconds < HEALTH_CACHE_TTL_SECONDS


@dataclass
class HealthCache[T]:
    """
    Health cache with async background refresh.

    Usage:
        cache = HealthCache[StatusResponse]()

        async def fetch_health():
            return await expensive_health_check()

        # Returns cached result, triggers background refresh
        result = await cache.get_or_refresh(fetch_health)
    """

    _cache: CacheEntry[T] | None = field(default=None, init=False)
    _refresh_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _refresh_task: asyncio.Task[Any] | None = field(default=None, init=False)
    _version: int = field(default=0, init=False)

    async def get_or_refresh(
        self,
        fetch_fn: Callable[[], Awaitable[T]],
        *,
        force_refresh: bool = False,
    ) -> T | None:
        """
        Get cached health data, triggering background refresh.

        If cache is fresh (< TTL), returns immediately.
        If cache is stale or empty, waits for refresh.
        Always triggers background refresh (deduped).

        Args:
            fetch_fn: Async function to fetch fresh health data
            force_refresh: If True, wait for fresh data even if cache exists

        Returns:
            Health data (cached or fresh)
        """
        # Trigger background refresh (fire and forget, deduped)
        self._schedule_refresh(fetch_fn)

        # If force refresh, wait for the refresh to complete
        if force_refresh:
            if self._refresh_task:
                await self._refresh_task
            return self._cache.data if self._cache else None

        # Return cached data if fresh
        if self._cache and self._cache.is_fresh:
            logger.debug(
                "Health cache hit: age=%.1fs, version=%d",
                self._cache.age_seconds,
                self._cache.version,
            )
            return self._cache.data

        # No cache or stale - wait for refresh
        if self._refresh_task:
            logger.debug("Health cache miss, waiting for refresh")
            await self._refresh_task

        return self._cache.data if self._cache else None

    def _schedule_refresh(self, fetch_fn: Callable[[], Awaitable[T]]) -> None:
        """Schedule a background refresh if not already running."""
        # Skip if refresh already in progress
        if self._refresh_task and not self._refresh_task.done():
            return

        # Create new refresh task
        self._refresh_task = asyncio.create_task(self._do_refresh(fetch_fn))

    async def _do_refresh(self, fetch_fn: Callable[[], Awaitable[T]]) -> None:
        """Perform the actual health check refresh."""
        async with self._refresh_lock:
            start = time.time()
            try:
                data = await fetch_fn()
                self._version += 1
                self._cache = CacheEntry(
                    data=data,
                    timestamp=time.time(),
                    version=self._version,
                )
                elapsed = (time.time() - start) * 1000
                logger.debug(
                    "Health cache refreshed: version=%d, took=%.1fms",
                    self._version,
                    elapsed,
                )
            except Exception as e:
                logger.warning("Health cache refresh failed: %s", e)
                # Keep stale cache on failure

    def invalidate(self) -> None:
        """Force cache invalidation."""
        self._cache = None
        self._version += 1
        logger.debug("Health cache invalidated, version=%d", self._version)

    @property
    def stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        return {
            "has_cache": self._cache is not None,
            "cache_age_seconds": self._cache.age_seconds if self._cache else None,
            "cache_is_fresh": self._cache.is_fresh if self._cache else False,
            "version": self._version,
            "ttl_seconds": HEALTH_CACHE_TTL_SECONDS,
            "refresh_in_progress": self._refresh_task is not None
            and not self._refresh_task.done(),
        }


# Module-level singleton for the status endpoint cache
_status_cache: HealthCache[Any] | None = None


def get_status_cache() -> HealthCache[Any]:
    """Get the singleton status cache instance."""
    global _status_cache
    if _status_cache is None:
        _status_cache = HealthCache[Any]()
    return _status_cache
