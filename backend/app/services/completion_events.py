"""Redis pub/sub event channel for async agentic completions.

Worker publishes progress to completion:progress:{task_id}.
API process subscribes and bridges to WebSocket via EventPublisher.
Results stored in Redis with 1hr TTL for polling.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)

RESULT_TTL_SECONDS = 3600
CHANNEL_PREFIX = "completion:progress"
RESULT_PREFIX = "completion:result"


class CompletionEventType(StrEnum):
    STARTED = "started"
    TURN_START = "turn_start"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    PROGRESS = "progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class CompletionProgressEvent:
    task_id: str
    session_id: str
    event_type: CompletionEventType
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    data: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str | bytes) -> CompletionProgressEvent:
        d = json.loads(raw)
        d["event_type"] = CompletionEventType(d["event_type"])
        return cls(**d)


def get_channel_name(task_id: str) -> str:
    return f"{CHANNEL_PREFIX}:{task_id}"


def _result_key(task_id: str) -> str:
    return f"{RESULT_PREFIX}:{task_id}"


class CompletionEventPublisher:
    """Sync Redis publisher for use inside Celery workers."""

    def __init__(self, task_id: str, session_id: str) -> None:
        self.task_id = task_id
        self.session_id = session_id
        self._redis: Any | None = None

    def _get_redis(self) -> Any:
        if self._redis is None:
            from redis import Redis

            from app.config import settings

            self._redis = Redis.from_url(settings.celery_broker_url)
        return self._redis

    def publish(self, event_type: CompletionEventType, data: dict[str, Any] | None = None) -> None:
        event = CompletionProgressEvent(
            task_id=self.task_id,
            session_id=self.session_id,
            event_type=event_type,
            data=data or {},
        )
        try:
            self._get_redis().publish(get_channel_name(self.task_id), event.to_json())
        except Exception:
            logger.warning("Failed to publish completion event %s for task %s", event_type, self.task_id, exc_info=True)

    def close(self) -> None:
        if self._redis is not None:
            import contextlib

            with contextlib.suppress(Exception):
                self._redis.close()
            self._redis = None


def store_task_result(task_id: str, result_dict: dict[str, Any]) -> None:
    """Store task result in Redis with TTL (sync, for worker)."""
    from redis import Redis

    from app.config import settings

    client = Redis.from_url(settings.celery_broker_url)
    try:
        client.setex(_result_key(task_id), RESULT_TTL_SECONDS, json.dumps(result_dict))
    finally:
        client.close()


async def get_task_result(task_id: str) -> dict[str, Any] | None:
    """Get stored task result from Redis (async, for API)."""
    from redis.asyncio import Redis as AsyncRedis

    from app.config import settings

    client = AsyncRedis.from_url(settings.celery_broker_url)
    try:
        raw = await client.get(_result_key(task_id))
        if raw is None:
            return None
        result: dict[str, Any] = json.loads(raw)
        return result
    finally:
        await client.close()
