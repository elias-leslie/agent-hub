"""Memory API - Session Analysis Endpoints.

Provides citation scanning and task outcome reporting for memory analytics.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.session_ingestion import FinalizeSessionRequest, finalize_session

logger = logging.getLogger(__name__)

router = APIRouter()


class AnalyzeRequest(BaseModel):
    """Request body for session analysis."""

    citation_prefixes: list[str] | None = Field(
        default=None,
        description="8-char hex UUID prefixes from CC transcript (optional for API sessions)",
    )
    feedback_tags: list[str] | None = Field(
        default=None,
        description="Raw feedback tag strings from CC transcript (optional)",
    )
    summary_tags: list[str] | None = Field(
        default=None,
        description="Raw [[S:outcome:description]] strings from CC transcript (optional)",
    )
    git_context: str | None = Field(
        default=None,
        description="Recent git log output for summary enrichment",
    )
    branch: str | None = Field(
        default=None,
        description="Git branch name",
    )
    transcript_path: str | None = Field(
        default=None,
        description="Path to a Claude Code or Codex JSONL transcript for transcript-aware parsing",
    )


class AnalyzeResponse(BaseModel):
    """Response from session analysis."""

    session_id: str
    citations_found: int
    citations_credited: int
    feedback_created: int = 0
    summary_stored: bool = False


class TaskOutcomeRequest(BaseModel):
    """Request body for task outcome reporting (session-scoped)."""

    succeeded: bool = Field(description="Whether the task succeeded")
    task_id: str | None = Field(default=None, description="Task ID for correlation")


class TaskOutcomeByTaskRequest(BaseModel):
    """Request body for task outcome reporting (task-scoped, finds sessions automatically)."""

    succeeded: bool = Field(description="Whether the task succeeded")
    task_id: str = Field(description="SummitFlow task ID")
    project_id: str | None = Field(
        default=None,
        description="Project ID for fallback session lookup when external_id not set",
    )
    started_at: str | None = Field(
        default=None,
        description="ISO timestamp of task start (for time-bounded session lookup)",
    )


class TaskOutcomeResponse(BaseModel):
    """Response from task outcome reporting."""

    session_id: str
    task_succeeded: bool
    metrics_updated: int
    memories_credited: int


class TaskOutcomeBatchResponse(BaseModel):
    """Response from task-scoped outcome reporting."""

    task_id: str
    task_succeeded: bool
    sessions_processed: int
    total_metrics_updated: int
    total_memories_credited: int


@router.post("/sessions/{session_id}/analyze")
async def analyze_session(
    session_id: str,
    request: AnalyzeRequest | None = None,
) -> AnalyzeResponse:
    """Analyze a session for memory citations and credit them.

    Two paths:
    - CC sessions: Send citation_prefixes extracted from JSONL transcript
    - API sessions: Omit body, citations extracted from session_events
    """
    try:
        result = await finalize_session(
            session_id=session_id,
            request=FinalizeSessionRequest(
                citation_prefixes=request.citation_prefixes if request else None,
                feedback_tags=request.feedback_tags if request else None,
                summary_tags=request.summary_tags if request else None,
                git_context=request.git_context if request else None,
                branch=request.branch if request else None,
                transcript_path=request.transcript_path if request else None,
            ) if request else None,
        )
        return AnalyzeResponse(
            session_id=result.session_id,
            citations_found=result.citations_found,
            citations_credited=result.citations_credited,
            feedback_created=result.feedback_created,
            summary_stored=result.summary_stored,
        )
    except Exception as e:
        logger.exception("Failed to analyze session %s", session_id)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to analyze session: {e}",
        ) from e


@router.post("/sessions/{session_id}/task-outcome")
async def report_task_outcome(
    session_id: str,
    request: TaskOutcomeRequest,
) -> TaskOutcomeResponse:
    """Report task outcome and credit loaded memories on success.

    Called by st done after task completion to propagate success/failure
    back to memory scoring.
    """
    from app.services.memory.session_analysis import process_task_outcome

    try:
        result = await process_task_outcome(
            session_id=session_id,
            succeeded=request.succeeded,
            task_id=request.task_id,
        )
        return TaskOutcomeResponse(
            session_id=result.session_id,
            task_succeeded=result.task_succeeded,
            metrics_updated=result.metrics_updated,
            memories_credited=result.memories_credited,
        )
    except Exception as e:
        logger.exception("Failed to process task outcome")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process task outcome: {e}",
        ) from e


@router.post("/task-outcome")
async def report_task_outcome_by_task(
    request: TaskOutcomeByTaskRequest,
) -> TaskOutcomeBatchResponse:
    """Report task outcome by task_id, finding all associated sessions automatically.

    Called by st done after task completion. Finds sessions via
    MemoryInjectionMetric.external_id matching the task_id.
    """
    from app.services.memory.session_analysis import find_sessions_for_task, process_task_outcome

    try:
        session_ids = await find_sessions_for_task(
            request.task_id,
            project_id=request.project_id,
            started_at=request.started_at,
        )

        total_metrics = 0
        total_memories = 0
        for sid in session_ids:
            result = await process_task_outcome(
                session_id=sid,
                succeeded=request.succeeded,
                task_id=request.task_id,
            )
            total_metrics += result.metrics_updated
            total_memories += result.memories_credited

        return TaskOutcomeBatchResponse(
            task_id=request.task_id,
            task_succeeded=request.succeeded,
            sessions_processed=len(session_ids),
            total_metrics_updated=total_metrics,
            total_memories_credited=total_memories,
        )
    except Exception as e:
        logger.exception("Failed to process task outcome")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process task outcome: {e}",
        ) from e
