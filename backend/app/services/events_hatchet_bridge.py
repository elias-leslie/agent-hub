"""
Hatchet workflow stream bridge for event publishing.

Subscribes to Hatchet workflow run streams and forwards events to EventPublisher.
"""

import asyncio
import json
import logging
from typing import Any

from .events_models import SessionEvent, SessionEventType

logger = logging.getLogger(__name__)


_COMPLETION_TO_SESSION_EVENT_MAP: dict[str, SessionEventType] = {
    "started": SessionEventType.SESSION_START,
    "turn_start": SessionEventType.MESSAGE,
    "tool_use": SessionEventType.TOOL_USE,
    "tool_result": SessionEventType.TOOL_USE,
    "progress": SessionEventType.MESSAGE,
    "completed": SessionEventType.COMPLETE,
    "failed": SessionEventType.ERROR,
    "cancelled": SessionEventType.ERROR,
}


def _map_completion_to_session_event(
    event_type_str: str,
    session_id: str,
    data: dict[str, Any],
) -> SessionEvent:
    """Map a CompletionProgressEvent type to a SessionEvent."""
    mapped_type = _COMPLETION_TO_SESSION_EVENT_MAP.get(
        event_type_str, SessionEventType.MESSAGE
    )
    return SessionEvent(
        event_type=mapped_type,
        session_id=session_id,
        data=data,
    )


_stream_bridge_tasks: dict[str, asyncio.Task[None]] = {}


async def _hatchet_stream_bridge_loop(task_id: str, workflow_run_id: str) -> None:
    """Subscribe to a Hatchet workflow run stream and forward to EventPublisher."""
    from app.hatchet_app import hatchet as hatchet_client

    from .events import get_event_publisher

    publisher = get_event_publisher()

    try:
        async for chunk in hatchet_client.runs.subscribe_to_stream(workflow_run_id):
            try:
                raw = chunk if isinstance(chunk, str) else chunk.decode()
                payload = json.loads(raw)
                session_id = payload.get("session_id", "")
                event_type_str = payload.get("event_type", "progress")
                event_data = payload.get("data", {})
                event_data["task_id"] = payload.get("task_id", "")

                session_event = _map_completion_to_session_event(
                    event_type_str, session_id, event_data
                )
                await publisher.publish(session_event)
            except Exception:
                logger.warning("Failed to process stream chunk", exc_info=True)
    except asyncio.CancelledError:
        logger.info("Hatchet stream bridge cancelled for task %s", task_id)
    except Exception:
        logger.error("Hatchet stream bridge error for task %s", task_id, exc_info=True)
    finally:
        _stream_bridge_tasks.pop(task_id, None)


async def start_hatchet_stream_bridge(task_id: str, workflow_run_id: str) -> None:
    """Start a per-task Hatchet stream bridge."""
    if task_id in _stream_bridge_tasks:
        return
    task = asyncio.create_task(_hatchet_stream_bridge_loop(task_id, workflow_run_id))
    _stream_bridge_tasks[task_id] = task
    logger.info("Hatchet stream bridge started for task %s (run %s)", task_id, workflow_run_id)


async def stop_all_stream_bridges() -> None:
    """Stop all active Hatchet stream bridges (shutdown cleanup)."""
    import contextlib

    tasks = list(_stream_bridge_tasks.values())
    for task in tasks:
        task.cancel()
    for task in tasks:
        with contextlib.suppress(asyncio.CancelledError):
            await task
    _stream_bridge_tasks.clear()
    logger.info("All Hatchet stream bridges stopped")
