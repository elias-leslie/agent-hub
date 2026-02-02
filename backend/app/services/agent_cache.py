"""Redis caching for agents."""

import json
import logging

import redis.asyncio as redis

from app.services.agent_dto import AgentDTO

logger = logging.getLogger(__name__)

# Cache configuration
CACHE_PREFIX = "agent-hub:agent:"
CACHE_TTL = 300  # 5 minutes


class AgentCache:
    """Redis cache for agents."""

    def __init__(self, redis_url: str):
        """Initialize cache.

        Args:
            redis_url: Redis connection URL
        """
        self._redis_url = redis_url
        self._client: redis.Redis | None = None  # type: ignore[type-arg]

    async def _get_redis(self) -> redis.Redis:  # type: ignore[type-arg]
        """Get or create Redis client."""
        if self._client is None:
            self._client = redis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._client

    def _cache_key(self, slug: str) -> str:
        """Generate cache key for an agent slug."""
        return f"{CACHE_PREFIX}{slug}"

    async def get(self, slug: str) -> AgentDTO | None:
        """Get agent from cache."""
        try:
            client = await self._get_redis()
            cached = await client.get(self._cache_key(slug))
            if cached:
                logger.debug(f"Cache hit for agent: {slug}")
                return AgentDTO.from_dict(json.loads(cached))
        except Exception as e:
            logger.warning(f"Cache get error for {slug}: {e}")
        return None

    async def set(self, agent: AgentDTO) -> None:
        """Set agent in cache."""
        try:
            client = await self._get_redis()
            await client.setex(
                self._cache_key(agent.slug),
                CACHE_TTL,
                json.dumps(agent.to_dict()),
            )
            logger.debug(f"Cached agent: {agent.slug}")
        except Exception as e:
            logger.warning(f"Cache set error for {agent.slug}: {e}")

    async def invalidate(self, slug: str) -> None:
        """Invalidate agent cache entry."""
        try:
            client = await self._get_redis()
            await client.delete(self._cache_key(slug))
            logger.debug(f"Invalidated cache for agent: {slug}")
        except Exception as e:
            logger.warning(f"Cache invalidate error for {slug}: {e}")

    async def close(self) -> None:
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None
