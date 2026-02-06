"""Admin Redis utilities for logging and state management."""

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import redis.asyncio as aioredis

from app.config import settings

if TYPE_CHECKING:
    from redis.asyncio.client import Redis as AsyncRedis

logger = logging.getLogger(__name__)

# Redis keys for admin state (multi-worker safe)
REDIS_KEY_BLOCKED_REQUESTS = "ah:admin:blocked_requests"  # List (LPUSH/LRANGE)
REDIS_KEY_AUDIT_LOG = "ah:admin:audit_log"  # List (LPUSH/LRANGE)
REDIS_KEY_UNKNOWN_CALLERS = "ah:admin:unknown_callers"  # Hash (HSET/HGETALL)

# Max entries in logs
MAX_BLOCKED_LOG_SIZE = 1000
MAX_AUDIT_LOG_SIZE = 2000

# TTL for log entries (24 hours - logs auto-expire)
LOG_TTL_SECONDS = 86400

# Global Redis client (lazy initialized)
_redis_client: "AsyncRedis[str] | None" = None


async def get_admin_redis() -> "AsyncRedis[str] | None":
    """Get or create Redis client for admin state.

    Returns None if Redis is unavailable (caller should handle gracefully).
    """
    global _redis_client
    if _redis_client is None:
        try:
            _redis_client = aioredis.from_url(
                settings.agent_hub_redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            # Test connection
            await _redis_client.ping()
            logger.debug("Redis connected for admin state")
        except Exception as e:
            logger.warning(f"Redis unavailable for admin state: {e}")
            return None
    return _redis_client


async def _serialize_entry(entry: dict[str, Any]) -> str:
    """Serialize an entry for Redis storage."""
    # Convert datetime to ISO format for JSON serialization
    serializable: dict[str, Any] = {}
    for key, value in entry.items():
        if isinstance(value, datetime):
            serializable[key] = value.isoformat()
        elif isinstance(value, set):
            serializable[key] = list(value)
        else:
            serializable[key] = value
    return json.dumps(serializable)


def _deserialize_entry(data: str) -> dict[str, Any]:
    """Deserialize an entry from Redis storage."""
    entry: dict[str, Any] = json.loads(data)
    # Convert ISO strings back to datetime where applicable
    if "timestamp" in entry and isinstance(entry["timestamp"], str):
        entry["timestamp"] = datetime.fromisoformat(entry["timestamp"])
    if "first_seen" in entry and entry["first_seen"] and isinstance(entry["first_seen"], str):
        entry["first_seen"] = datetime.fromisoformat(entry["first_seen"])
    if "last_seen" in entry and entry["last_seen"] and isinstance(entry["last_seen"], str):
        entry["last_seen"] = datetime.fromisoformat(entry["last_seen"])
    return entry


async def log_blocked_request(
    client_name: str | None,
    source_path: str | None,
    block_reason: str,
    endpoint: str,
) -> None:
    """Log a blocked request for admin visibility.

    Uses Redis LIST for multi-worker safe storage.
    """
    redis = await get_admin_redis()
    if redis is None:
        logger.warning("Redis unavailable, skipping blocked request log")
        return

    entry = {
        "timestamp": datetime.now(UTC),
        "client_name": client_name,
        "source_path": source_path,
        "block_reason": block_reason,
        "endpoint": endpoint,
    }

    try:
        # LPUSH adds to head of list (newest first)
        await redis.lpush(REDIS_KEY_BLOCKED_REQUESTS, await _serialize_entry(entry))
        # LTRIM keeps only the most recent entries
        await redis.ltrim(REDIS_KEY_BLOCKED_REQUESTS, 0, MAX_BLOCKED_LOG_SIZE - 1)
        # Set TTL on first entry (refreshed with each LPUSH)
        await redis.expire(REDIS_KEY_BLOCKED_REQUESTS, LOG_TTL_SECONDS)
    except Exception as e:
        logger.warning(f"Failed to log blocked request to Redis: {e}")


async def log_request_audit(
    endpoint: str,
    method: str,
    client_name: str | None,
    source_path: str | None,
    user_agent: str | None,
    referer: str | None,
    client_ip: str | None,
    status: str,  # "allowed", "blocked", "unknown_client"
) -> None:
    """Log all requests to sensitive endpoints for audit visibility.

    This provides visibility into WHO is calling Agent Hub, even if they
    don't provide proper X-Source-Client headers.

    Uses Redis LIST for audit log and Redis HASH for unknown caller stats.
    """
    redis = await get_admin_redis()
    if redis is None:
        logger.warning("Redis unavailable, skipping audit log")
        return

    now = datetime.now(UTC)

    entry = {
        "timestamp": now,
        "endpoint": endpoint,
        "method": method,
        "client_name": client_name,
        "source_path": source_path,
        "user_agent": user_agent,
        "referer": referer,
        "client_ip": client_ip,
        "status": status,
    }

    try:
        # Log to audit list (LPUSH for newest-first ordering)
        await redis.lpush(REDIS_KEY_AUDIT_LOG, await _serialize_entry(entry))
        await redis.ltrim(REDIS_KEY_AUDIT_LOG, 0, MAX_AUDIT_LOG_SIZE - 1)
        await redis.expire(REDIS_KEY_AUDIT_LOG, LOG_TTL_SECONDS)

        # Track unknown callers (no X-Source-Client)
        if not client_name or client_name == "<unknown>":
            # Create a fingerprint from available info
            fingerprint = f"{user_agent or 'no-ua'}|{referer or 'no-ref'}|{client_ip or 'no-ip'}"

            # Get existing stats or create new
            existing = await redis.hget(REDIS_KEY_UNKNOWN_CALLERS, fingerprint)
            if existing:
                stats = _deserialize_entry(existing)
                # Convert lists back to sets for manipulation
                stats["endpoints"] = set(stats.get("endpoints", []))
                stats["user_agents"] = set(stats.get("user_agents", []))
            else:
                stats = {
                    "count": 0,
                    "first_seen": now,
                    "last_seen": None,
                    "endpoints": set(),
                    "user_agents": set(),
                }

            stats["count"] += 1
            stats["last_seen"] = now
            stats["endpoints"].add(endpoint)
            if user_agent:
                stats["user_agents"].add(user_agent)

            # Save back to Redis
            await redis.hset(
                REDIS_KEY_UNKNOWN_CALLERS,
                fingerprint,
                await _serialize_entry(stats),
            )
            await redis.expire(REDIS_KEY_UNKNOWN_CALLERS, LOG_TTL_SECONDS)
    except Exception as e:
        logger.warning(f"Failed to log audit to Redis: {e}")
