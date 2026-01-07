"""
Response caching service for identical API requests.

Caches completion responses in Redis to avoid redundant API calls.
"""

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import redis.asyncio as redis

from app.config import settings

logger = logging.getLogger(__name__)

# Default cache TTL (5 minutes)
DEFAULT_CACHE_TTL = 300

# Stale-if-error TTL for degraded mode (1 hour - use older cached responses when providers down)
STALE_IF_ERROR_TTL = 3600

# Cache key prefix
CACHE_PREFIX = "agent-hub:response:"

# Fallback cache prefix (separate storage for stale-if-error responses)
FALLBACK_PREFIX = "agent-hub:fallback:"


@dataclass
class CacheStats:
    """Cache statistics."""

    hits: int = 0
    misses: int = 0
    total_requests: int = 0
    fallback_hits: int = 0
    fallback_misses: int = 0

    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate."""
        if self.total_requests == 0:
            return 0.0
        return self.hits / self.total_requests

    @property
    def fallback_usage(self) -> int:
        """Total fallback responses served."""
        return self.fallback_hits


@dataclass
class CachedResponse:
    """A cached response with metadata."""

    content: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    finish_reason: str | None
    cached_at: str
    cache_key: str
    is_fallback: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "content": self.content,
            "model": self.model,
            "provider": self.provider,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "finish_reason": self.finish_reason,
            "cached_at": self.cached_at,
            "cache_key": self.cache_key,
            "is_fallback": self.is_fallback,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CachedResponse":
        """Create from dictionary."""
        return cls(
            content=data["content"],
            model=data["model"],
            provider=data["provider"],
            input_tokens=data["input_tokens"],
            output_tokens=data["output_tokens"],
            finish_reason=data.get("finish_reason"),
            cached_at=data["cached_at"],
            cache_key=data["cache_key"],
            is_fallback=data.get("is_fallback", False),
        )


class ResponseCache:
    """Redis-based response cache for API completions."""

    def __init__(
        self,
        redis_url: str | None = None,
        default_ttl: int = DEFAULT_CACHE_TTL,
    ):
        """
        Initialize response cache.

        Args:
            redis_url: Redis connection URL. Falls back to settings.
            default_ttl: Default TTL in seconds (default 5 minutes).
        """
        self._redis_url = redis_url or settings.agent_hub_redis_url
        self._default_ttl = default_ttl
        self._client: redis.Redis | None = None
        self._stats = CacheStats()

    async def _get_client(self) -> redis.Redis:
        """Get or create Redis client."""
        if self._client is None:
            self._client = redis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._client

    def _generate_cache_key(
        self,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> str:
        """
        Generate cache key from request parameters.

        Creates a deterministic hash from all parameters that affect the response.
        """
        # Create a canonical representation of the request
        key_data = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        # Sort keys for deterministic JSON
        key_json = json.dumps(key_data, sort_keys=True)
        # Generate SHA256 hash
        key_hash = hashlib.sha256(key_json.encode()).hexdigest()[:32]
        return f"{CACHE_PREFIX}{key_hash}"

    async def get(
        self,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> CachedResponse | None:
        """
        Get cached response if available.

        Args:
            model: Model identifier
            messages: Request messages
            max_tokens: Max tokens parameter
            temperature: Temperature parameter

        Returns:
            CachedResponse if found, None otherwise
        """
        self._stats.total_requests += 1

        try:
            client = await self._get_client()
            cache_key = self._generate_cache_key(model, messages, max_tokens, temperature)

            cached_data = await client.get(cache_key)
            if cached_data:
                self._stats.hits += 1
                logger.info(f"Cache hit: {cache_key}")
                data = json.loads(cached_data)
                return CachedResponse.from_dict(data)

            self._stats.misses += 1
            return None

        except Exception as e:
            logger.warning(f"Cache get error: {e}")
            self._stats.misses += 1
            return None

    async def set(
        self,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
        content: str,
        provider: str,
        input_tokens: int,
        output_tokens: int,
        finish_reason: str | None = None,
        ttl: int | None = None,
        stale_if_error_ttl: int | None = None,
    ) -> str:
        """
        Cache a response.

        Args:
            model: Model identifier
            messages: Request messages
            max_tokens: Max tokens parameter
            temperature: Temperature parameter
            content: Response content
            provider: Provider name
            input_tokens: Input token count
            output_tokens: Output token count
            finish_reason: Why generation stopped
            ttl: Custom TTL in seconds (uses default if not specified)
            stale_if_error_ttl: TTL for fallback cache during outages (uses STALE_IF_ERROR_TTL if not specified)

        Returns:
            Cache key used
        """
        try:
            client = await self._get_client()
            cache_key = self._generate_cache_key(model, messages, max_tokens, temperature)

            cached_response = CachedResponse(
                content=content,
                model=model,
                provider=provider,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                finish_reason=finish_reason,
                cached_at=datetime.utcnow().isoformat(),
                cache_key=cache_key,
            )

            # Store in primary cache with short TTL
            await client.setex(
                cache_key,
                ttl or self._default_ttl,
                json.dumps(cached_response.to_dict()),
            )

            # Also store in fallback cache with longer TTL for stale-if-error
            fallback_key = cache_key.replace(CACHE_PREFIX, FALLBACK_PREFIX)
            await client.setex(
                fallback_key,
                stale_if_error_ttl or STALE_IF_ERROR_TTL,
                json.dumps(cached_response.to_dict()),
            )

            logger.info(f"Cached response: {cache_key}")
            return cache_key

        except Exception as e:
            logger.warning(f"Cache set error: {e}")
            return ""

    async def get_fallback(
        self,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> CachedResponse | None:
        """
        Get stale cached response for fallback during provider outages.

        Uses longer-lived fallback cache when primary cache misses
        and providers are unavailable.

        Args:
            model: Model identifier
            messages: Request messages
            max_tokens: Max tokens parameter
            temperature: Temperature parameter

        Returns:
            CachedResponse if found (with is_fallback=True), None otherwise
        """
        try:
            client = await self._get_client()
            cache_key = self._generate_cache_key(model, messages, max_tokens, temperature)
            fallback_key = cache_key.replace(CACHE_PREFIX, FALLBACK_PREFIX)

            cached_data = await client.get(fallback_key)
            if cached_data:
                self._stats.fallback_hits += 1
                logger.info(f"Fallback cache hit: {fallback_key}")
                data = json.loads(cached_data)
                response = CachedResponse.from_dict(data)
                response.is_fallback = True
                return response

            self._stats.fallback_misses += 1
            return None

        except Exception as e:
            logger.warning(f"Fallback cache get error: {e}")
            self._stats.fallback_misses += 1
            return None

    async def invalidate(self, cache_key: str) -> bool:
        """
        Invalidate a cached response.

        Args:
            cache_key: Key to invalidate

        Returns:
            True if key was deleted, False otherwise
        """
        try:
            client = await self._get_client()
            result = await client.delete(cache_key)
            return result > 0
        except Exception as e:
            logger.warning(f"Cache invalidate error: {e}")
            return False

    async def clear_all(self) -> int:
        """
        Clear all cached responses.

        Returns:
            Number of keys deleted
        """
        try:
            client = await self._get_client()
            keys = await client.keys(f"{CACHE_PREFIX}*")
            if keys:
                return await client.delete(*keys)
            return 0
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
