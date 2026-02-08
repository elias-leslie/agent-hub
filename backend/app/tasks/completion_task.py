"""Celery task for async agentic completion execution.

Runs complete_internal() in a Celery worker with fresh DB session.
Memory injection happens in the API endpoint before enqueuing.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded

from app.services.completion_events import (
    CompletionEventPublisher,
    CompletionEventType,
    store_task_result,
)

logger = logging.getLogger(__name__)


def _result_to_dict(result: Any, task_id: str) -> dict[str, Any]:
    """Convert CompletionInternalResult to JSON-serializable dict."""
    return {
        "task_id": task_id,
        "content": result.content,
        "model": result.model,
        "provider": result.provider,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "finish_reason": result.finish_reason,
        "session_id": result.session_id,
        "memory_uuids": result.memory_uuids,
        "cited_uuids": result.cited_uuids,
        "from_cache": result.from_cache,
        "thinking_content": result.thinking_content,
        "thinking_tokens": result.thinking_tokens,
        "turns": result.turns,
        "tool_calls_count": result.tool_calls_count,
        "status": result.status,
        "error": result.error,
        "container_id": result.container_id,
        "progress_log": [
            {
                "turn": p.turn,
                "status": p.status,
                "message": p.message,
                "tool_calls": p.tool_calls or [],
                "tool_results": p.tool_results or [],
                "thinking": p.thinking,
            }
            for p in (result.progress_log or [])
        ],
    }


async def _run_completion(
    task_id: str,
    publisher: CompletionEventPublisher,
    **kwargs: Any,
) -> dict[str, Any]:
    """Run agentic completion with fresh DB session."""
    from app.api.complete.core import AgentProgress, complete_internal
    from app.api.complete.schemas import MessageInput
    from app.db import async_session

    raw_messages = kwargs.pop("user_messages_for_db", None)
    user_messages_for_db: list[MessageInput] | None = None
    if raw_messages:
        user_messages_for_db = [MessageInput(**m) for m in raw_messages]

    async def progress_callback(progress: AgentProgress) -> None:
        event_type = CompletionEventType.PROGRESS
        if progress.status == "turn_start":
            event_type = CompletionEventType.TURN_START
        elif progress.status == "tool_use":
            event_type = CompletionEventType.TOOL_USE
        elif progress.status == "tool_result":
            event_type = CompletionEventType.TOOL_RESULT
        publisher.publish(event_type, {
            "turn": progress.turn,
            "status": progress.status,
            "message": progress.message,
        })

    async with async_session() as db:
        result = await complete_internal(
            db=db,
            user_messages_for_db=user_messages_for_db,
            progress_callback=progress_callback,
            use_memory=False,
            **kwargs,
        )

    return _result_to_dict(result, task_id)


@shared_task(
    bind=True,
    retry_kwargs={"max_retries": 0},
    track_started=True,
)
def run_agentic_completion(self: Any, /, **kwargs: Any) -> dict[str, Any]:
    """Execute an agentic completion loop in a Celery worker.

    Args:
        **kwargs: All complete_internal() parameters as JSON-serializable values.
            Must include 'task_id' and 'session_id'.
    """
    task_id = kwargs.pop("task_id")
    session_id = kwargs.get("session_id", "")
    publisher = CompletionEventPublisher(task_id, session_id)

    try:
        publisher.publish(CompletionEventType.STARTED)

        loop = asyncio.new_event_loop()
        try:
            result_dict = loop.run_until_complete(
                _run_completion(task_id=task_id, publisher=publisher, **kwargs)
            )
        finally:
            loop.close()

        store_task_result(task_id, result_dict)
        publisher.publish(CompletionEventType.COMPLETED, {
            "turns": result_dict.get("turns", 1),
            "tool_calls_count": result_dict.get("tool_calls_count", 0),
        })

        return result_dict

    except SoftTimeLimitExceeded:
        logger.warning("Agentic completion timed out for task %s", task_id)
        timeout_result = {
            "task_id": task_id,
            "session_id": session_id,
            "status": "failed",
            "error": "Task exceeded time limit",
        }
        store_task_result(task_id, timeout_result)
        publisher.publish(CompletionEventType.FAILED, {"error": "Task exceeded time limit"})
        raise
    except Exception as e:
        logger.exception("Agentic completion failed for task %s: %s", task_id, e)
        error_result = {
            "task_id": task_id,
            "session_id": session_id,
            "status": "failed",
            "error": str(e),
        }
        store_task_result(task_id, error_result)
        publisher.publish(CompletionEventType.FAILED, {"error": str(e)})
        raise
    finally:
        publisher.close()
