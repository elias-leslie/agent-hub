"""Memory API - Dashboard Endpoints."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from starlette.responses import StreamingResponse

from app.db import _get_session_factory
from app.models import Session
from app.services.memory.analytics_models import MemoryAnalyticsDashboard
from app.services.memory.service import MemoryCategory, MemoryScope

from .memory_dashboard_helpers import SummarizeRequest, dispatch_to_hatchet, run_sync_summarize
from .memory_dependencies import get_scope_params
from .memory_lookback import parse_memory_lookback

logger = logging.getLogger(__name__)
router = APIRouter()

# Strong references to background tasks to prevent GC before completion (RUF006)
_background_tasks: set[Any] = set()


async def _store_summary_request_context(
    session_id: str,
    branch: str | None,
    transcript_path: str | None,
    git_context: str | None,
) -> None:
    """Persist summary request context for future transcript-aware reanalysis."""
    if not any((branch, transcript_path, git_context)):
        return

    try:
        async with _get_session_factory()() as db:
            row = await db.execute(select(Session).where(Session.id == session_id))
            session = row.scalar_one_or_none()
            if not session:
                return

            provider_metadata = dict(session.provider_metadata or {})
            summary_context = dict(provider_metadata.get("summary_context") or {})

            if branch is not None:
                summary_context["branch"] = branch
            if transcript_path is not None:
                summary_context["transcript_path"] = transcript_path
            if git_context is not None:
                summary_context["git_context"] = git_context

            provider_metadata["summary_context"] = summary_context
            session.provider_metadata = provider_metadata
            await db.commit()
    except Exception as e:
        logger.warning("Failed to persist summary context for %s: %s", session_id, e)


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
        logger.exception("Failed to get memory timeline")
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
        logger.exception("Failed to get sessions with memory")
        raise HTTPException(status_code=500, detail=f"Failed to get sessions: {e}") from e


@router.get("/analytics/top-memories")
async def get_top_memories_endpoint(
    group_id: Annotated[str | None, Query(description="Filter by group_id (omit for all groups)")] = None,
    sort_by: Annotated[str, Query(description="Sort field: utility_score, referenced_count, lifecycle_score, loaded_count")] = "utility_score",
    limit: Annotated[int, Query(ge=1, le=50, description="Max results")] = 8,
) -> Any:
    from app.services.memory.analytics_service import get_top_memories

    try:
        return await get_top_memories(group_id=group_id, sort_by=sort_by, limit=limit)
    except Exception as e:
        logger.exception("Failed to get top memories")
        raise HTTPException(status_code=500, detail=f"Failed to get top memories: {e}") from e


@router.get("/analytics/tier-changes")
async def get_tier_changes(
    days: Annotated[int, Query(ge=1, le=90, description="Days to look back")] = 30,
    lookback: Annotated[
        str | None,
        Query(description="Compact lookback window: 1h, 1d, 7d, 14d, 30d"),
    ] = None,
) -> Any:
    from app.services.memory.analytics_queries import get_tier_changes_summary

    try:
        lookback_delta, _ = parse_memory_lookback(lookback, fallback_days=days)
        return await get_tier_changes_summary(lookback_delta=lookback_delta)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get tier changes: {e}") from e
 
 
@router.get("/analytics", response_model=MemoryAnalyticsDashboard)
async def get_analytics(
    group_id: Annotated[str | None, Query(description="Filter by group_id (omit for all groups)")] = None,
    days: Annotated[int, Query(ge=1, le=90, description="Days to look back for recent activity")] = 30,
    lookback: Annotated[
        str | None,
        Query(description="Compact recent-activity window: 1h, 1d, 7d, 14d, 30d"),
    ] = None,
    sort_by: Annotated[
        str,
        Query(description="Top memory sort field: utility_score, referenced_count, lifecycle_score, loaded_count"),
    ] = "utility_score",
) -> Any:
    from app.services.memory.analytics_service import get_memory_dashboard

    try:
        lookback_delta, lookback_label = parse_memory_lookback(lookback, fallback_days=days)
        return await get_memory_dashboard(
            group_id=group_id,
            lookback_delta=lookback_delta,
            lookback_label=lookback_label,
            top_memories_sort_by=sort_by,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("Failed to get memory analytics")
        raise HTTPException(status_code=500, detail=f"Failed to get analytics: {e}") from e


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

    # Short-circuit: if inline summary already stored, skip LLM summarizer
    async with _get_session_factory()() as db:
        row = await db.execute(
            select(Session.summary_oneliner).where(Session.id == session_id)
        )
        existing_summary = row.scalar_one_or_none()
        if existing_summary:
            return JSONResponse(
                status_code=200,
                content={"status": "already_summarized", "session_id": session_id},
            )

    branch = request.branch if request else None
    transcript_path = request.transcript_path if request else None
    git_context = request.git_context if request else None
    async_dispatch = request.async_dispatch if request else False
    await _store_summary_request_context(
        session_id,
        branch=branch,
        transcript_path=transcript_path,
        git_context=git_context,
    )

    if async_dispatch:
        dispatched = await dispatch_to_hatchet(
            _background_tasks, session_id, branch, transcript_path, git_context
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
        transcript_path=transcript_path,
        git_context=git_context,
    )


@router.get("/continuity")
async def get_continuity_context(
    project_id: Annotated[str | None, Query(description="Filter to a specific project")] = None,
    days: Annotated[int, Query(ge=1, le=30, description="Days to look back")] = 7,
    max_sessions: Annotated[int, Query(ge=1, le=50, description="Max sessions to include")] = 10,
    include_cross_project: Annotated[
        bool,
        Query(description="Explicitly include summaries from other projects"),
    ] = False,
) -> Any:
    from app.services.memory.continuity_injector import build_continuity_context
    try:
        return await build_continuity_context(
            project_id=project_id,
            days=days,
            max_sessions=max_sessions,
            include_cross_project=include_cross_project,
            include_live_sessions=True,
            allow_unscoped=project_id is None,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to build continuity context: {e}") from e
