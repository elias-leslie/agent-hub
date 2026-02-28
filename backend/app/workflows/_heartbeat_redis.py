"""Redis-backed state helpers for the persona heartbeat."""

from __future__ import annotations

from datetime import UTC, datetime

# Redis key constants
REDIS_LAST_RUN_KEY = "persona:heartbeat:last_run"
REDIS_LAST_MODEL_REVIEW_KEY = "persona:heartbeat:last_model_review"


def _get_redis_client():
    """Create and return a Redis async client."""
    import redis.asyncio as redis

    from app.config import settings

    return redis.from_url(
        settings.agent_hub_redis_url, encoding="utf-8", decode_responses=True
    )


async def record_heartbeat(did_model_review: bool = False) -> None:
    """Store current timestamp as last heartbeat run (and model review if done)."""
    client = _get_redis_client()
    try:
        now = datetime.now(UTC).isoformat()
        await client.set(REDIS_LAST_RUN_KEY, now)
        if did_model_review:
            await client.set(REDIS_LAST_MODEL_REVIEW_KEY, now)
    finally:
        await client.close()


async def get_model_review_status() -> tuple[bool, str]:
    """Check if a model review is due (more than 7 days since last one).

    Returns (is_due, status_label).
    """
    client = _get_redis_client()
    try:
        last_review_str = await client.get(REDIS_LAST_MODEL_REVIEW_KEY)
        if not last_review_str:
            return True, "never reviewed"
        last_review = datetime.fromisoformat(last_review_str)
        days_ago = (datetime.now(UTC) - last_review).total_seconds() / 86400
        if days_ago >= 7:
            return True, f"last review {days_ago:.0f} days ago"
        return False, f"last review {days_ago:.1f} days ago"
    finally:
        await client.close()


async def check_redis_elapsed(interval_minutes: int) -> bool:
    """Return True if enough time has elapsed since the last heartbeat run."""
    client = _get_redis_client()
    try:
        last_run_str = await client.get(REDIS_LAST_RUN_KEY)
        if not last_run_str:
            return True
        last_run = datetime.fromisoformat(last_run_str)
        elapsed = (datetime.now(UTC) - last_run).total_seconds() / 60
        return elapsed >= interval_minutes
    finally:
        await client.close()


__all__ = [
    "REDIS_LAST_MODEL_REVIEW_KEY",
    "REDIS_LAST_RUN_KEY",
    "check_redis_elapsed",
    "get_model_review_status",
    "record_heartbeat",
]
