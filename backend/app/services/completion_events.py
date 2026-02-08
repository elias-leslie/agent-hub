"""Event types and result storage for async agentic completions.

Results stored in Redis with 1hr TTL for polling.
Progress streaming handled by Hatchet ctx.aio_put_stream().
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


def _result_key(task_id: str) -> str:
    return f"{RESULT_PREFIX}:{task_id}"


def store_task_result(task_id: str, result_dict: dict[str, Any]) -> None:
    """Store task result in Redis with TTL (sync, for worker)."""
    from redis import Redis

    from app.config import settings

    client = Redis.from_url(settings.agent_hub_redis_url)
    try:
        client.setex(_result_key(task_id), RESULT_TTL_SECONDS, json.dumps(result_dict))
    finally:
        client.close()


async def get_task_result(task_id: str) -> dict[str, Any] | None:
    """Get stored task result from Redis (async, for API)."""
    from redis.asyncio import Redis as AsyncRedis

    from app.config import settings

    client = AsyncRedis.from_url(settings.agent_hub_redis_url)
    try:
        raw = await client.get(_result_key(task_id))
        if raw is None:
            return None
        result: dict[str, Any] = json.loads(raw)
        return result
    finally:
        await client.close()
