"""Redis-backed state helpers for the persona heartbeat."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TypedDict

logger = logging.getLogger(__name__)

# Redis key constants
REDIS_LAST_RUN_KEY = "persona:heartbeat:last_run"
REDIS_LAST_MODEL_REVIEW_KEY = "persona:heartbeat:last_model_review"
REDIS_METRICS_KEY = "persona:heartbeat:metrics"
REDIS_RUNNING_KEY = "persona:heartbeat:running"
REDIS_DAILY_COUNT_PREFIX = "persona:heartbeat:daily"
_DAILY_COUNT_TTL = 14 * 86400  # 14 days
_RUNNING_TTL = 1800  # 30 minutes, matches execution timeout
_SPIKE_THRESHOLD = 50  # 3x normal rate at 60min interval


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


async def record_heartbeat_metrics(
    *,
    session_id: str,
    format_compliant: bool,
    summary_stored: bool,
    turns: int,
    tool_calls: int,
    had_error: bool,
) -> None:
    """Store heartbeat health metrics in Redis."""
    client = _get_redis_client()
    try:
        now = datetime.now(UTC)

        # Update latest metrics hash
        await client.hset(
            REDIS_METRICS_KEY,
            mapping={
                "last_run": now.isoformat(),
                "session_id": session_id,
                "format_compliant": str(format_compliant),
                "summary_stored": str(summary_stored),
                "turns": str(turns),
                "tool_calls": str(tool_calls),
                "had_error": str(had_error),
            },
        )

        # Increment daily counter
        date_key = f"{REDIS_DAILY_COUNT_PREFIX}:{now.strftime('%Y-%m-%d')}"
        count = await client.incr(date_key)
        if count == 1:
            await client.expire(date_key, _DAILY_COUNT_TTL)

        if count > _SPIKE_THRESHOLD:
            logger.warning(
                "Heartbeat spike: %d runs today (threshold=%d)",
                count,
                _SPIKE_THRESHOLD,
            )
    except Exception:
        logger.exception("Failed to record heartbeat metrics")
    finally:
        await client.close()


async def set_heartbeat_running() -> None:
    """Mark the heartbeat as currently running with a timestamp and TTL."""
    client = _get_redis_client()
    try:
        await client.set(REDIS_RUNNING_KEY, datetime.now(UTC).isoformat(), ex=_RUNNING_TTL)
    except Exception:
        logger.exception("Failed to set heartbeat running lock")
    finally:
        await client.close()


async def clear_heartbeat_running() -> None:
    """Clear the running lock when the heartbeat finishes."""
    client = _get_redis_client()
    try:
        await client.delete(REDIS_RUNNING_KEY)
    except Exception:
        logger.exception("Failed to clear heartbeat running lock")
    finally:
        await client.close()


class HeartbeatRunningInfo(TypedDict):
    started_at: str
    elapsed_seconds: int


async def get_heartbeat_running_info() -> HeartbeatRunningInfo | None:
    """Return running state info or None if not running."""
    client = _get_redis_client()
    try:
        started_str = await client.get(REDIS_RUNNING_KEY)
        if not started_str:
            return None
        started = datetime.fromisoformat(started_str)
        elapsed = (datetime.now(UTC) - started).total_seconds()
        return {"started_at": started_str, "elapsed_seconds": round(elapsed)}
    finally:
        await client.close()


async def get_last_run_info() -> str | None:
    """Return the ISO timestamp of the last completed heartbeat run, or None."""
    client = _get_redis_client()
    try:
        return await client.get(REDIS_LAST_RUN_KEY)
    finally:
        await client.close()


class HeartbeatMetrics(TypedDict, total=False):
    last_run: str
    session_id: str
    format_compliant: str
    summary_stored: str
    turns: str
    tool_calls: str
    had_error: str


async def get_heartbeat_metrics() -> HeartbeatMetrics | None:
    """Return the latest heartbeat metrics hash, or None if no data."""
    client = _get_redis_client()
    try:
        data = await client.hgetall(REDIS_METRICS_KEY)
        return data if data else None
    finally:
        await client.close()


__all__ = [
    "REDIS_LAST_MODEL_REVIEW_KEY",
    "REDIS_LAST_RUN_KEY",
    "REDIS_RUNNING_KEY",
    "check_redis_elapsed",
    "clear_heartbeat_running",
    "get_heartbeat_metrics",
    "get_heartbeat_running_info",
    "get_last_run_info",
    "get_model_review_status",
    "record_heartbeat",
    "record_heartbeat_metrics",
    "set_heartbeat_running",
]
