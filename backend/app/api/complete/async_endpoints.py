"""Async completion task status and cancellation endpoints."""

from __future__ import annotations

import logging
from typing import Any

from celery.result import AsyncResult
from fastapi import APIRouter, HTTPException

from app.api.complete.schemas import (
    AsyncTaskStatusResponse,
    CompletionResponse,
    UsageInfo,
)
from app.api.orchestration_models import AgentProgressInfo
from app.services.completion_events import get_task_result

logger = logging.getLogger(__name__)

router = APIRouter()

CELERY_STATE_MAP = {
    "PENDING": "pending",
    "STARTED": "started",
    "SUCCESS": "completed",
    "FAILURE": "failed",
    "REVOKED": "cancelled",
    "RETRY": "pending",
}


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
            AgentProgressInfo(
                turn=p.get("turn", 0),
                status=p.get("status", ""),
                message=p.get("message", ""),
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

    celery_result: AsyncResult[dict[str, Any]] = AsyncResult(task_id)
    celery_state = celery_result.state
    status = CELERY_STATE_MAP.get(celery_state, "unknown")

    if stored and stored.get("status") == "failed":
        return AsyncTaskStatusResponse(
            task_id=task_id,
            session_id=stored.get("session_id"),
            status="failed",
            error=stored.get("error"),
        )

    if stored and status in ("completed", "pending"):
        status = "completed"
        return AsyncTaskStatusResponse(
            task_id=task_id,
            session_id=stored.get("session_id"),
            status="completed",
            result=_build_completion_response(stored),
        )

    if status == "pending" and not stored:
        status = "unknown"

    return AsyncTaskStatusResponse(
        task_id=task_id,
        session_id=None,
        status=status,
    )


@router.delete("/complete/tasks/{task_id}/cancel")
async def cancel_task(task_id: str) -> dict[str, str]:
    """Cancel a running async completion task."""
    celery_result: AsyncResult[dict[str, Any]] = AsyncResult(task_id)

    if celery_result.state in ("SUCCESS", "FAILURE", "REVOKED"):
        raise HTTPException(
            status_code=409,
            detail=f"Task already in terminal state: {celery_result.state}",
        )

    celery_result.revoke(terminate=True, signal="SIGTERM")
    return {"task_id": task_id, "status": "cancelled"}
