"""Redis-backed state helpers for the persona heartbeat."""

from __future__ import annotations

import json
import logging
import os
import socket
from datetime import UTC, datetime
from typing import TypedDict
from uuid import uuid4

logger = logging.getLogger(__name__)

# Redis key constants
REDIS_LAST_RUN_KEY = "persona:heartbeat:last_run"
REDIS_LAST_MODEL_REVIEW_KEY = "persona:heartbeat:last_model_review"
REDIS_METRICS_KEY = "persona:heartbeat:metrics"
REDIS_RUNNING_KEY = "persona:heartbeat:running"
REDIS_STATE_KEY = "persona:heartbeat:state"
REDIS_RECALL_CACHE_PREFIX = "persona:heartbeat:recall"
REDIS_DAILY_COUNT_PREFIX = "persona:heartbeat:daily"
_DAILY_COUNT_TTL = 14 * 86400  # 14 days
_RUNNING_TTL = 7500  # 2h workflow timeout + 5m slack
_RECALL_CACHE_TTL = 15 * 60
_SPIKE_THRESHOLD = 50  # 3x normal rate at 60min interval


def _get_redis_client():
    """Create and return a Redis async client."""
    import redis.asyncio as redis

    from app.config import settings

    return redis.from_url(
        settings.agent_hub_redis_url, encoding="utf-8", decode_responses=True
    )


async def record_heartbeat_attempt(*, session_id: str | None = None) -> None:
    """Store current timestamp as the last heartbeat attempt."""
    client = _get_redis_client()
    try:
        now = datetime.now(UTC).isoformat()
        mapping: dict[str, str] = {
            "last_attempt": now,
            "last_skip_reason": "",
            "last_error": "",
        }
        if session_id:
            mapping["last_session_id"] = session_id
        await client.hset(REDIS_STATE_KEY, mapping=mapping)
    finally:
        await client.close()


async def record_heartbeat_success(
    *,
    session_id: str | None = None,
    did_model_review: bool = False,
) -> None:
    """Store current timestamp as the last successful heartbeat run."""
    client = _get_redis_client()
    try:
        now = datetime.now(UTC).isoformat()
        mapping: dict[str, str] = {
            "last_attempt": now,
            "last_success": now,
            "last_skip_reason": "",
            "last_error": "",
        }
        if session_id:
            mapping["last_session_id"] = session_id
        await client.set(REDIS_LAST_RUN_KEY, now)
        await client.hset(REDIS_STATE_KEY, mapping=mapping)
        if did_model_review:
            await client.set(REDIS_LAST_MODEL_REVIEW_KEY, now)
    finally:
        await client.close()


async def record_heartbeat_skip(reason: str, *, session_id: str | None = None) -> None:
    """Store the latest skipped heartbeat attempt and its reason."""
    client = _get_redis_client()
    try:
        now = datetime.now(UTC).isoformat()
        mapping: dict[str, str] = {
            "last_attempt": now,
            "last_skip_reason": reason,
            "last_error": "",
        }
        if session_id:
            mapping["last_session_id"] = session_id
        await client.hset(REDIS_STATE_KEY, mapping=mapping)
    finally:
        await client.close()


async def record_heartbeat_error(error: str, *, session_id: str | None = None) -> None:
    """Store the latest failed heartbeat attempt and its error."""
    client = _get_redis_client()
    try:
        now = datetime.now(UTC).isoformat()
        mapping: dict[str, str] = {
            "last_attempt": now,
            "last_error": error,
            "last_skip_reason": "",
        }
        if session_id:
            mapping["last_session_id"] = session_id
        await client.hset(REDIS_STATE_KEY, mapping=mapping)
    finally:
        await client.close()


async def get_model_review_status() -> tuple[bool, str]:
    """Check if a model review is due (more than 7 days since last one)."""
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
    """Return True if enough time has elapsed since the last successful heartbeat run."""
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


async def set_heartbeat_running(
    *,
    session_id: str | None = None,
    claim_token: str | None = None,
    owner_pid: int | None = None,
    owner_host: str | None = None,
    trigger: str | None = None,
    project_id: str | None = None,
    only_if_missing: bool = False,
) -> str | None:
    """Claim the heartbeat running lock and return the claim token on success."""
    client = _get_redis_client()
    resolved_claim_token = claim_token or str(uuid4())
    try:
        payload = json.dumps(
            {
                "started_at": datetime.now(UTC).isoformat(),
                "session_id": session_id,
                "claim_token": resolved_claim_token,
                "owner_pid": owner_pid if owner_pid is not None else os.getpid(),
                "owner_host": owner_host or socket.gethostname(),
                "trigger": trigger,
                "project_id": project_id,
            }
        )
        claimed = await client.set(
            REDIS_RUNNING_KEY,
            payload,
            ex=_RUNNING_TTL,
            nx=only_if_missing,
        )
        if only_if_missing and not claimed:
            return None
        return resolved_claim_token
    except Exception:
        logger.exception("Failed to set heartbeat running lock")
        return None
    finally:
        await client.close()


async def clear_heartbeat_running(
    *,
    claim_token: str | None = None,
    session_id: str | None = None,
) -> bool:
    """Clear the running lock when the heartbeat finishes."""
    client = _get_redis_client()
    try:
        payload = await client.get(REDIS_RUNNING_KEY)
        if not payload:
            return False
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            parsed = {"started_at": payload, "session_id": None}
        current_claim_token = str(parsed.get("claim_token") or "") or None
        current_session_id = str(parsed.get("session_id") or "") or None
        if claim_token and current_claim_token != claim_token:
            return False
        if session_id and current_session_id != session_id:
            return False
        await client.delete(REDIS_RUNNING_KEY)
        return True
    except Exception:
        logger.exception("Failed to clear heartbeat running lock")
        return False
    finally:
        await client.close()


class HeartbeatRunningInfo(TypedDict, total=False):
    started_at: str
    elapsed_seconds: int
    session_id: str | None
    claim_token: str | None
    owner_pid: int | None
    owner_host: str | None
    trigger: str | None
    project_id: str | None


async def get_heartbeat_running_info() -> HeartbeatRunningInfo | None:
    """Return running state info or None if not running."""
    client = _get_redis_client()
    try:
        payload = await client.get(REDIS_RUNNING_KEY)
        if not payload:
            return None
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            parsed = {"started_at": payload, "session_id": None}
        started_str = str(parsed.get("started_at") or "")
        if not started_str:
            return None
        started = datetime.fromisoformat(started_str)
        elapsed = (datetime.now(UTC) - started).total_seconds()
        return {
            "started_at": started_str,
            "elapsed_seconds": round(elapsed),
            "session_id": parsed.get("session_id"),
            "claim_token": parsed.get("claim_token"),
            "owner_pid": (
                int(parsed["owner_pid"])
                if parsed.get("owner_pid") not in (None, "")
                else None
            ),
            "owner_host": parsed.get("owner_host"),
            "trigger": parsed.get("trigger"),
            "project_id": parsed.get("project_id"),
        }
    finally:
        await client.close()


async def get_last_run_info() -> str | None:
    """Return the ISO timestamp of the last successful heartbeat run, or None."""
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


class HeartbeatState(TypedDict, total=False):
    last_attempt: str
    last_success: str
    last_skip_reason: str
    last_error: str
    last_session_id: str


class HeartbeatRecallCache(TypedDict, total=False):
    generated_at: str
    project_id: str | None
    recent_heartbeat_digest: str
    recent_idle_history: str
    improvement_signal_digest: str


def _recall_cache_key(project_id: str | None) -> str:
    normalized = project_id or "__all__"
    return f"{REDIS_RECALL_CACHE_PREFIX}:{normalized}"


async def get_heartbeat_metrics() -> HeartbeatMetrics | None:
    """Return the latest heartbeat metrics hash, or None if no data."""
    client = _get_redis_client()
    try:
        data = await client.hgetall(REDIS_METRICS_KEY)
        return data if data else None
    finally:
        await client.close()


async def get_heartbeat_state() -> HeartbeatState | None:
    """Return the latest heartbeat state hash, or None if no data."""
    client = _get_redis_client()
    try:
        data = await client.hgetall(REDIS_STATE_KEY)
        return data if data else None
    finally:
        await client.close()


async def get_heartbeat_recall_cache(project_id: str | None = None) -> HeartbeatRecallCache | None:
    """Return prefetched heartbeat recall sections for the given project scope."""
    client = _get_redis_client()
    try:
        payload = await client.get(_recall_cache_key(project_id))
        if not payload:
            return None
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            logger.warning("Failed to decode heartbeat recall cache for project=%s", project_id)
            return None
        return data if isinstance(data, dict) else None
    finally:
        await client.close()


async def set_heartbeat_recall_cache(
    *,
    project_id: str | None = None,
    recent_heartbeat_digest: str = "",
    recent_idle_history: str = "",
    improvement_signal_digest: str = "",
) -> None:
    """Persist prefetched heartbeat recall sections for the next run."""
    client = _get_redis_client()
    try:
        payload = json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "project_id": project_id,
                "recent_heartbeat_digest": recent_heartbeat_digest,
                "recent_idle_history": recent_idle_history,
                "improvement_signal_digest": improvement_signal_digest,
            }
        )
        await client.set(_recall_cache_key(project_id), payload, ex=_RECALL_CACHE_TTL)
    except Exception:
        logger.exception("Failed to persist heartbeat recall cache")
    finally:
        await client.close()


__all__ = [
    "REDIS_LAST_MODEL_REVIEW_KEY",
    "REDIS_LAST_RUN_KEY",
    "REDIS_RUNNING_KEY",
    "check_redis_elapsed",
    "clear_heartbeat_running",
    "get_heartbeat_metrics",
    "get_heartbeat_recall_cache",
    "get_heartbeat_running_info",
    "get_heartbeat_state",
    "get_last_run_info",
    "get_model_review_status",
    "record_heartbeat_attempt",
    "record_heartbeat_error",
    "record_heartbeat_metrics",
    "record_heartbeat_skip",
    "record_heartbeat_success",
    "set_heartbeat_recall_cache",
    "set_heartbeat_running",
]
