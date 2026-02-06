from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class CaptureEvent(BaseModel):
    event_type: str  # "observation" | "heartbeat"
    timestamp: str
    data: dict[str, Any]


class CaptureStreamManager:
    def __init__(self) -> None:
        self._queues: list[asyncio.Queue[CaptureEvent]] = []
        self._lock = asyncio.Lock()

    async def subscribe(self) -> AsyncGenerator[str]:
        queue: asyncio.Queue[CaptureEvent] = asyncio.Queue(maxsize=100)
        async with self._lock:
            self._queues.append(queue)
        connected = CaptureEvent(
            event_type="connected",
            timestamp=datetime.now(UTC).isoformat(),
            data={"subscribers": len(self._queues)},
        )
        yield f"event: {connected.event_type}\ndata: {connected.model_dump_json()}\n\n"
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"event: {event.event_type}\ndata: {event.model_dump_json()}\n\n"
                except TimeoutError:
                    heartbeat = CaptureEvent(
                        event_type="heartbeat",
                        timestamp=datetime.now(UTC).isoformat(),
                        data={},
                    )
                    yield f"event: heartbeat\ndata: {heartbeat.model_dump_json()}\n\n"
        finally:
            async with self._lock:
                self._queues.remove(queue)

    async def broadcast(self, event: CaptureEvent) -> None:
        async with self._lock:
            dead_queues: list[asyncio.Queue[CaptureEvent]] = []
            for q in self._queues:
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    dead_queues.append(q)
            for q in dead_queues:
                self._queues.remove(q)


# Singleton
_manager: CaptureStreamManager | None = None


def get_capture_stream() -> CaptureStreamManager:
    global _manager
    if _manager is None:
        _manager = CaptureStreamManager()
    return _manager
