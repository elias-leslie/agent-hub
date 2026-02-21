"""Per-agent execution quotas backed by Redis counters."""

import logging

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

# Redis key prefixes
_TOKEN_KEY = "quota:tokens:{agent}:{day}"  # daily token counter
_REQUEST_KEY = "quota:requests:{agent}:{hour}"  # hourly request counter

# TTLs (seconds) — slightly longer than the window to handle edge cases
_DAY_TTL = 86400 + 3600  # 25 hours
_HOUR_TTL = 3600 + 600  # 70 minutes

_redis: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    """Get or create async Redis client for quota tracking."""
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.agent_hub_redis_url, decode_responses=True)
    return _redis


class QuotaExceededError(Exception):
    """Raised when an agent's quota is exceeded."""

    def __init__(self, agent_slug: str, quota_type: str, limit: int, current: int):
        self.agent_slug = agent_slug
        self.quota_type = quota_type
        self.limit = limit
        self.current = current
        super().__init__(
            f"Quota exceeded for agent '{agent_slug}': "
            f"{quota_type} limit {limit}, current usage {current}"
        )


async def check_request_quota(agent_slug: str, hourly_limit: int | None) -> None:
    """Check and increment the hourly request counter.

    Raises QuotaExceededError if the agent has exceeded its hourly request limit.
    """
    if not hourly_limit or hourly_limit <= 0:
        return

    from datetime import UTC, datetime

    r = _get_redis()
    hour = datetime.now(UTC).strftime("%Y%m%d%H")
    key = _REQUEST_KEY.format(agent=agent_slug, hour=hour)

    current = await r.incr(key)
    if current == 1:
        await r.expire(key, _HOUR_TTL)

    if current > hourly_limit:
        raise QuotaExceededError(agent_slug, "hourly_requests", hourly_limit, current)

    logger.debug(f"Quota: agent={agent_slug} requests={current}/{hourly_limit} (hour={hour})")


async def check_token_quota(agent_slug: str, daily_limit: int | None) -> None:
    """Check if the agent has exceeded its daily token budget.

    Unlike request quota, this is a soft check (read-only) since we don't know
    the token count until after execution. The post-execution tracker will
    increment the counter.

    Raises QuotaExceededError if the agent has already exceeded its daily budget.
    """
    if not daily_limit or daily_limit <= 0:
        return

    from datetime import UTC, datetime

    r = _get_redis()
    day = datetime.now(UTC).strftime("%Y%m%d")
    key = _TOKEN_KEY.format(agent=agent_slug, day=day)

    current = int(await r.get(key) or 0)
    if current >= daily_limit:
        raise QuotaExceededError(agent_slug, "daily_tokens", daily_limit, current)

    logger.debug(f"Quota: agent={agent_slug} tokens={current}/{daily_limit} (day={day})")


async def record_token_usage(agent_slug: str, tokens: int) -> None:
    """Record token usage after completion. Increments the daily counter."""
    if tokens <= 0:
        return

    from datetime import UTC, datetime

    r = _get_redis()
    day = datetime.now(UTC).strftime("%Y%m%d")
    key = _TOKEN_KEY.format(agent=agent_slug, day=day)

    new_total = await r.incrby(key, tokens)
    # Set TTL only on first increment (when key was just created)
    if new_total == tokens:
        await r.expire(key, _DAY_TTL)

    logger.debug(f"Quota: recorded {tokens} tokens for agent={agent_slug}, total={new_total}")


async def get_quota_usage(agent_slug: str) -> dict[str, int]:
    """Get current quota usage for an agent."""
    from datetime import UTC, datetime

    r = _get_redis()
    now = datetime.now(UTC)
    day = now.strftime("%Y%m%d")
    hour = now.strftime("%Y%m%d%H")

    token_key = _TOKEN_KEY.format(agent=agent_slug, day=day)
    request_key = _REQUEST_KEY.format(agent=agent_slug, hour=hour)

    tokens_used = int(await r.get(token_key) or 0)
    requests_used = int(await r.get(request_key) or 0)

    return {
        "tokens_today": tokens_used,
        "requests_this_hour": requests_used,
    }
