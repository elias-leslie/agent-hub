"""Memory API - Episode CRUD Endpoints."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.services.memory import MemoryService
from app.services.memory.service import MemoryCategory, MemoryListResult, MemoryStats

from .memory_dependencies import get_memory_svc, resolve_episode_uuid
from .memory_episodes_handlers import (
    handle_add_episode,
    handle_delete_episode,
    handle_get_episode,
    handle_list_episode_revisions,
    handle_restore_episode_revision,
    handle_update_episode,
    handle_update_episode_properties,
)
from .memory_episodes_query import (
    handle_get_episode_citations,
    handle_get_memory_stats,
    handle_list_episodes,
    handle_list_memory_scopes,
    handle_memory_health,
)
from .memory_episodes_search import (
    handle_get_similar_episodes,
    handle_search_memory,
    handle_text_search_memory,
)
from .memory_schemas import (
    AddEpisodeRequest,
    AddEpisodeResponse,
    DeleteEpisodeResponse,
    EpisodeDetailResponse,
    HealthResponse,
    MemoryRestoreRequest,
    MemoryReviewRunRequest,
    MemoryReviewRunResponse,
    MemoryRevisionListResponse,
    SearchResponse,
    UpdateEpisodePropertiesRequest,
    UpdateEpisodePropertiesResponse,
    UpdateEpisodeRequest,
    UpdateEpisodeResponse,
)

router = APIRouter()


@router.post("/add", response_model=AddEpisodeResponse)
async def add_episode(
    request: AddEpisodeRequest,
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
) -> AddEpisodeResponse:
    """Add an episode to semantic memory. Optionally set tier and preserve stats."""
    return await handle_add_episode(request, memory)


@router.get("/list", response_model=MemoryListResult)
async def list_episodes(
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
    limit: Annotated[int, Query(ge=1, le=300, description="Max episodes per page")] = 50,
    cursor: Annotated[str | None, Query(description="Timestamp cursor for pagination")] = None,
    category: Annotated[MemoryCategory | None, Query(description="Filter by category")] = None,
    all_groups: Annotated[bool, Query(description="Include all groups instead of current scope")] = False,
    sort_by: Annotated[str, Query(description="Sort field: updated_at or created_at")] = "updated_at",
    sort_order: Annotated[str, Query(description="Sort direction: asc or desc")] = "desc",
) -> MemoryListResult:
    """List episodes with cursor-based pagination (reverse chronological order)."""
    normalized_sort_by = sort_by if sort_by in {"updated_at", "created_at"} else "updated_at"
    normalized_sort_order = sort_order if sort_order in {"asc", "desc"} else "desc"
    return await handle_list_episodes(
        memory,
        limit,
        cursor,
        category,
        all_groups,
        normalized_sort_by,
        normalized_sort_order,
    )


@router.get("/stats", response_model=MemoryStats)
async def get_memory_stats(
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
    all_groups: Annotated[bool, Query(description="Include all groups instead of current scope")] = False,
) -> MemoryStats:
    """Get memory statistics (total count, category breakdown, last updated)."""
    return await handle_get_memory_stats(memory, all_groups)


@router.get("/scopes")
async def list_memory_scopes(
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
) -> Any:
    """List all memory scopes (global, project, task) with episode counts."""
    return await handle_list_memory_scopes(memory)


@router.get("/search", response_model=SearchResponse)
async def search_memory(
    query: Annotated[str, Query(..., description="Search query")],
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
    limit: Annotated[int, Query(ge=1, le=300, description="Max results")] = 10,
    min_score: Annotated[float, Query(ge=0.0, le=1.0, description="Minimum relevance score")] = 0.0,
    category: Annotated[MemoryCategory | None, Query(description="Filter by tier")] = None,
) -> SearchResponse:
    """Hybrid search: semantic + text keyword matching across all scopes."""
    return await handle_search_memory(query, memory, limit, min_score, category)


@router.get("/text-search", response_model=MemoryListResult)
async def text_search_memory(
    query: Annotated[str, Query(..., min_length=1, description="Text search query")],
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
    limit: Annotated[int, Query(ge=1, le=300, description="Max results")] = 50,
    category: Annotated[MemoryCategory | None, Query(description="Filter by category")] = None,
) -> MemoryListResult:
    """Case-insensitive substring search on content, name, summary, tier (for management UI)."""
    return await handle_text_search_memory(query, memory, limit, category)


@router.get("/episode/{episode_id}", response_model=EpisodeDetailResponse)
async def get_episode(
    full_uuid: Annotated[str, Depends(resolve_episode_uuid)],
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
) -> EpisodeDetailResponse:
    """Get episode details (content, metadata, usage stats). Accepts UUID or 8-char prefix."""
    return await handle_get_episode(full_uuid, memory)


@router.delete("/episode/{episode_id}", response_model=DeleteEpisodeResponse)
async def delete_episode(
    full_uuid: Annotated[str, Depends(resolve_episode_uuid)],
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
    change_reason: Annotated[str | None, Query(description="Why this episode is being deleted")] = None,
) -> DeleteEpisodeResponse:
    """Delete episode and clean up orphaned entities/edges. Accepts UUID or 8-char prefix."""
    return await handle_delete_episode(full_uuid, memory, change_reason=change_reason)


@router.patch("/episode/{episode_id}", response_model=UpdateEpisodeResponse)
async def update_episode(
    full_uuid: Annotated[str, Depends(resolve_episode_uuid)],
    request: UpdateEpisodeRequest,
) -> UpdateEpisodeResponse:
    """Update episode content and/or tier in place. Accepts UUID or 8-char prefix."""
    return await handle_update_episode(full_uuid, request)


@router.patch("/episode/{episode_id}/properties", response_model=UpdateEpisodePropertiesResponse)
async def update_episode_properties(
    full_uuid: Annotated[str, Depends(resolve_episode_uuid)],
    request: UpdateEpisodePropertiesRequest,
) -> UpdateEpisodePropertiesResponse:
    """Update episode properties (pinned, auto_inject, display_order, triggers, summary)."""
    return await handle_update_episode_properties(full_uuid, request)


@router.get("/episode/{episode_id}/citations")
async def get_episode_citations(
    full_uuid: Annotated[str, Depends(resolve_episode_uuid)],
    limit: Annotated[int, Query(ge=1, le=100, description="Max citations")] = 20,
) -> Any:
    """Get injection sessions where this episode was cited."""
    return await handle_get_episode_citations(full_uuid, limit)


@router.get("/episode/{episode_id}/revisions", response_model=MemoryRevisionListResponse)
async def list_episode_revisions(
    episode_id: str,
    limit: Annotated[int, Query(ge=1, le=100, description="Max revisions")] = 20,
) -> MemoryRevisionListResponse:
    """List immutable revision history for an episode by current or historical UUID prefix."""
    return await handle_list_episode_revisions(episode_id, limit=limit)


@router.post("/episode/{episode_id}/revisions/{revision_id}/restore", response_model=UpdateEpisodeResponse)
async def restore_episode_revision(
    episode_id: str,
    revision_id: str,
    request: MemoryRestoreRequest,
) -> UpdateEpisodeResponse:
    """Restore an episode to a historical revision by current or historical UUID prefix."""
    return await handle_restore_episode_revision(episode_id, revision_id, request)


@router.get("/episode/{episode_id}/similar")
async def get_similar_episodes(
    full_uuid: Annotated[str, Depends(resolve_episode_uuid)],
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
    limit: Annotated[int, Query(ge=1, le=20, description="Max similar episodes")] = 5,
    min_score: Annotated[float, Query(ge=0.0, le=1.0, description="Min similarity")] = 0.7,
) -> Any:
    """Find episodes with similar content via embedding search."""
    return await handle_get_similar_episodes(full_uuid, memory, limit, min_score)


@router.get("/health", response_model=HealthResponse)
async def memory_health(
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
) -> HealthResponse:
    """Check memory system health (PostgreSQL + pgvector connection status)."""
    return await handle_memory_health(memory)


@router.post("/review/run", response_model=MemoryReviewRunResponse)
async def run_memory_review(
    request: MemoryReviewRunRequest,
) -> MemoryReviewRunResponse:
    """Run one dedicated-agent memory review batch."""
    from app.db import async_session
    from app.services.memory.review_agent import run_memory_review_batch

    async with async_session() as db:
        result = await run_memory_review_batch(
            db=db,
            batch_limit=request.batch_limit,
            cadence_days=request.cadence_days,
            reviewer_agent_slug=request.reviewer_agent_slug,
            reviewer_model_id=request.reviewer_model_id,
            dry_run=request.dry_run,
            force_all=request.force_all,
            include_archived=request.include_archived,
            only_missing_compact=request.only_missing_compact,
        )
        await db.commit()
    return MemoryReviewRunResponse(**result.__dict__)
