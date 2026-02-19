"""Memory API - Dashboard Endpoints."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.responses import StreamingResponse

from app.services.memory.service import MemoryCategory, MemoryScope

from .memory_dashboard_helpers import SummarizeRequest, dispatch_to_hatchet, run_sync_summarize
from .memory_dependencies import get_scope_params

logger = logging.getLogger(__name__)
router = APIRouter()

# Strong references to background tasks to prevent GC before completion (RUF006)
_background_tasks: set[Any] = set()


@router.get("/timeline")
async def get_timeline(
    scope_params: Annotated[tuple[MemoryScope, str | None], Depends(get_scope_params)],
    category: Annotated[MemoryCategory | None, Query(description="Filter by category")] = None,
    limit: Annotated[int, Query(ge=1, le=10000, description="Max episodes")] = 10000,
) -> Any:
    from app.services.memory.memory_utils import build_group_id
    from app.services.memory.timeline_service import get_timeline_groups

    scope, scope_id = scope_params
    group_id = build_group_id(scope, scope_id)
    try:
        return await get_timeline_groups(
            group_id=group_id,
            scope=scope,
            scope_id=scope_id,
            category=category,
            limit=limit,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get timeline: {e}") from e


@router.get("/sessions-with-memory")
async def get_sessions_with_memory_endpoint(
    limit: Annotated[int, Query(ge=1, le=500, description="Max sessions per page")] = 50,
    offset: Annotated[int, Query(ge=0, description="Offset for pagination")] = 0,
) -> Any:
    from app.services.memory.session_memory_service import get_sessions_with_memory

    try:
        return await get_sessions_with_memory(limit=limit, offset=offset)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get sessions: {e}") from e


@router.get("/analytics")
async def get_analytics(
    group_id: Annotated[str | None, Query(description="Filter by group_id (omit for all groups)")] = None,
    days: Annotated[int, Query(ge=1, le=90, description="Days to look back for trend")] = 30,
) -> Any:
    from app.services.memory.analytics_service import get_memory_analytics

    try:
        return await get_memory_analytics(group_id=group_id, days=days)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get analytics: {e}") from e


@router.get("/analytics/top-memories")
async def get_top_memories_endpoint(
    group_id: Annotated[str | None, Query(description="Filter by group_id (omit for all groups)")] = None,
    sort_by: Annotated[str, Query(description="Sort field: utility_score, referenced_count, success_count, loaded_count")] = "utility_score",
    limit: Annotated[int, Query(ge=1, le=50, description="Max results")] = 8,
) -> Any:
    from app.services.memory.analytics_service import get_top_memories

    try:
        return await get_top_memories(group_id=group_id, sort_by=sort_by, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get top memories: {e}") from e


@router.get("/capture/stream")
async def capture_stream() -> StreamingResponse:
    from app.services.memory.capture_stream import get_capture_stream
    stream = get_capture_stream()
    return StreamingResponse(
        stream.subscribe(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/sessions/{session_id}/summarize")
async def summarize_session(
    session_id: str,
    request: SummarizeRequest | None = None,
) -> Any:
    from fastapi.responses import JSONResponse

    branch = request.branch if request else None
    is_worktree = request.is_worktree if request else False
    transcript_path = request.transcript_path if request else None
    git_context = request.git_context if request else None
    async_dispatch = request.async_dispatch if request else False

    if async_dispatch:
        dispatched = await dispatch_to_hatchet(
            _background_tasks, session_id, branch, is_worktree, transcript_path, git_context
        )
        if dispatched:
            return JSONResponse(
                status_code=202,
                content={"status": "dispatched", "session_id": session_id},
            )

    return await run_sync_summarize(
        _background_tasks,
        session_id,
        project_id=request.project_id if request else None,
        branch=branch,
        is_worktree=is_worktree,
        transcript_path=transcript_path,
        git_context=git_context,
    )


@router.get("/continuity")
async def get_continuity_context(
    project_id: Annotated[str | None, Query(description="Filter to a specific project")] = None,
    days: Annotated[int, Query(ge=1, le=30, description="Days to look back")] = 7,
    max_sessions: Annotated[int, Query(ge=1, le=50, description="Max sessions to include")] = 10,
) -> Any:
    from app.services.memory.continuity_injector import build_continuity_context
    try:
        return await build_continuity_context(
            project_id=project_id,
            days=days,
            max_sessions=max_sessions,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to build continuity context: {e}") from e
