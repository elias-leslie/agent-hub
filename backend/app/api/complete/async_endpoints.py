"""Async completion task status and cancellation endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from redis.asyncio import Redis as AsyncRedis

from app.api.complete.progress import AgentProgress
from app.api.complete.schemas import (
    AsyncTaskStatusResponse,
    CompletionResponse,
    UsageInfo,
)
from app.config import settings
from app.services.completion_events import get_task_result

logger = logging.getLogger(__name__)

router = APIRouter()


def _build_completion_response(stored: dict[str, Any]) -> CompletionResponse:
    """Map stored result dict back to CompletionResponse."""
    return CompletionResponse(
        content=stored.get("content", ""),
        model=stored.get("model", "unknown"),
        provider=stored.get("provider", "unknown"),
        usage=UsageInfo(
            input_tokens=stored.get("input_tokens", 0),
            output_tokens=stored.get("output_tokens", 0),
            total_tokens=stored.get("input_tokens", 0) + stored.get("output_tokens", 0),
        ),
        session_id=stored.get("session_id", ""),
        finish_reason=stored.get("finish_reason"),
        turns=stored.get("turns", 1),
        tool_calls_count=stored.get("tool_calls_count", 0),
        memory_facts_injected=len(stored.get("memory_uuids", [])),
        memory_uuids=",".join(stored.get("memory_uuids", [])) or None,
        cited_uuids=stored.get("cited_uuids", []),
        trace_id=stored.get("trace_id"),
        progress_log=[
            AgentProgress(
                turn=p.get("turn", 0),
                status=p.get("status", ""),
                message=p.get("message", ""),
                topic=p.get("topic"),
                tool_calls=p.get("tool_calls", []),
                tool_results=p.get("tool_results", []),
                thinking=p.get("thinking"),
            )
            for p in stored.get("progress_log", [])
        ]
        or None,
    )


@router.get("/complete/tasks/{task_id}", response_model=AsyncTaskStatusResponse)
async def get_task_status(task_id: str) -> AsyncTaskStatusResponse:
    """Get status and result of an async completion task."""
    stored = await get_task_result(task_id)

    if stored and stored.get("status") == "failed":
        return AsyncTaskStatusResponse(
            task_id=task_id,
            session_id=stored.get("session_id"),
            status="failed",
            error=stored.get("error"),
        )

    if stored:
        return AsyncTaskStatusResponse(
            task_id=task_id,
            session_id=stored.get("session_id"),
            status="completed",
            result=_build_completion_response(stored),
        )

    # No result yet - check if we have a workflow run ID (task is in progress)
    redis_client = AsyncRedis.from_url(settings.agent_hub_redis_url)
    try:
        run_id = await redis_client.get(f"hatchet:run:{task_id}")
    finally:
        await redis_client.close()

    if run_id:
        return AsyncTaskStatusResponse(
            task_id=task_id,
            session_id=None,
            status="started",
        )

    return AsyncTaskStatusResponse(
        task_id=task_id,
        session_id=None,
        status="unknown",
    )


@router.delete("/complete/tasks/{task_id}/cancel")
async def cancel_task(task_id: str) -> dict[str, str]:
    """Cancel a running async completion task."""
    redis_client = AsyncRedis.from_url(settings.agent_hub_redis_url)
    try:
        run_id_raw = await redis_client.get(f"hatchet:run:{task_id}")
    finally:
        await redis_client.close()

    if not run_id_raw:
        # Check if already completed
        stored = await get_task_result(task_id)
        if stored:
            raise HTTPException(
                status_code=409,
                detail="Task already in terminal state",
            )
        raise HTTPException(
            status_code=404,
            detail="Task not found",
        )

    workflow_run_id = run_id_raw.decode() if isinstance(run_id_raw, bytes) else run_id_raw

    from app.hatchet_app import hatchet as hatchet_client

    try:
        await hatchet_client.runs.aio_cancel(workflow_run_id)
    except Exception as e:
        logger.warning("Failed to cancel Hatchet run %s: %s", workflow_run_id, e)

    return {"task_id": task_id, "status": "cancelled"}
