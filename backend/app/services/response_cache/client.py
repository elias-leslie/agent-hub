"""Redis-based response cache for API completions."""

import json
import logging
from datetime import UTC, datetime

import redis.asyncio as redis

from app.config import settings

from .cache_key import generate_cache_key, get_fallback_key
from .constants import (
    CACHE_PREFIX,
    DEFAULT_CACHE_TTL,
    STALE_IF_ERROR_TTL,
)
from .models import CachedResponse, CacheStats

logger = logging.getLogger(__name__)


class ResponseCache:
    """Redis-based response cache for API completions."""

    def __init__(
        self,
        redis_url: str | None = None,
        default_ttl: int = DEFAULT_CACHE_TTL,
    ):
        """Initialize response cache with Redis connection and TTL."""
        self._redis_url = redis_url or settings.agent_hub_redis_url
        self._default_ttl = default_ttl
        self._client: redis.Redis | None = None  # type: ignore[type-arg]
        self._stats = CacheStats()

    async def _get_client(self) -> redis.Redis:  # type: ignore[type-arg]
        """Get or create Redis client."""
        if self._client is None:
            self._client = redis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._client

    async def get(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
    ) -> CachedResponse | None:
        """Get cached response if available."""
        self._stats.total_requests += 1
        cache_key = generate_cache_key(model, messages, temperature)

        try:
            client = await self._get_client()
            cached_data = await client.get(cache_key)
            if not cached_data:
                self._stats.misses += 1
                return None

            self._stats.hits += 1
            logger.info(f"Cache hit: {cache_key}")
            return CachedResponse.from_dict(json.loads(cached_data))

        except Exception as e:
            logger.warning(f"Cache get error: {e}")
            self._stats.misses += 1
            return None

    async def get_fallback(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
    ) -> CachedResponse | None:
        """Get stale cached response for fallback during provider outages."""
        cache_key = generate_cache_key(model, messages, temperature)
        fallback_key = get_fallback_key(cache_key)

        try:
            client = await self._get_client()
            cached_data = await client.get(fallback_key)
            if not cached_data:
                self._stats.fallback_misses += 1
                return None

            self._stats.fallback_hits += 1
            logger.info(f"Fallback cache hit: {fallback_key}")
            response = CachedResponse.from_dict(json.loads(cached_data))
            response.is_fallback = True
            return response

        except Exception as e:
            logger.warning(f"Fallback cache get error: {e}")
            self._stats.fallback_misses += 1
            return None

    async def set(
        self,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        content: str,
        provider: str,
        input_tokens: int,
        output_tokens: int,
        finish_reason: str | None = None,
        ttl: int | None = None,
        stale_if_error_ttl: int | None = None,
    ) -> str:
        """Cache a response in both primary and fallback stores."""
        try:
            client = await self._get_client()
            cache_key = generate_cache_key(model, messages, temperature)

            response_json = json.dumps(
                CachedResponse(
                    content=content,
                    model=model,
                    provider=provider,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    finish_reason=finish_reason,
                    cached_at=datetime.now(UTC).isoformat(),
                    cache_key=cache_key,
                ).to_dict()
            )

            # Store in primary cache with short TTL
            await client.setex(cache_key, ttl or self._default_ttl, response_json)

            # Also store in fallback cache with longer TTL
            await client.setex(
                get_fallback_key(cache_key),
                stale_if_error_ttl or STALE_IF_ERROR_TTL,
                response_json,
            )

            logger.info(f"Cached response: {cache_key}")
            return cache_key

        except Exception as e:
            logger.warning(f"Cache set error: {e}")
            return ""

    async def invalidate(self, cache_key: str) -> bool:
        """Invalidate a cached response."""
        try:
            client = await self._get_client()
            return await client.delete(cache_key) > 0
        except Exception as e:
            logger.warning(f"Cache invalidate error: {e}")
            return False

    async def clear_all(self) -> int:
        """Clear all cached responses."""
        try:
            client = await self._get_client()
            keys = await client.keys(f"{CACHE_PREFIX}*")
            return await client.delete(*keys) if keys else 0
        except Exception as e:
            logger.warning(f"Cache clear error: {e}")
            return 0

    def get_stats(self) -> CacheStats:
        """Get cache statistics."""
        return self._stats

    def reset_stats(self) -> None:
        """Reset cache statistics."""
        self._stats = CacheStats()

    async def close(self) -> None:
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None


# Singleton instance
_response_cache: ResponseCache | None = None


def get_response_cache() -> ResponseCache:
    """Get the singleton response cache instance."""
    global _response_cache
    if _response_cache is None:
        _response_cache = ResponseCache()
    return _response_cache
