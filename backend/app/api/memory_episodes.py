"""Memory API - Episode CRUD Endpoints."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.services.memory import MemoryService
from app.services.memory.episode_creator import get_episode_creator
from app.services.memory.service import MemoryCategory, MemoryListResult, MemoryStats

from .memory_dependencies import get_memory_svc, resolve_episode_uuid
from .memory_schemas import (
    AddEpisodeRequest,
    AddEpisodeResponse,
    DeleteEpisodeResponse,
    EpisodeDetailResponse,
    HealthResponse,
    SearchResponse,
    UpdateEpisodePropertiesRequest,
    UpdateEpisodePropertiesResponse,
)

router = APIRouter()


@router.post("/add", response_model=AddEpisodeResponse)
async def add_episode(
    request: AddEpisodeRequest,
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
) -> AddEpisodeResponse:
    """
    Add an episode to the knowledge graph memory.

    Episodes are processed to extract entities and relationships,
    which are stored in the knowledge graph for semantic retrieval.

    If injection_tier is provided, the episode's tier is set after creation.

    If preserve_stats_from is provided, usage stats (helpful_count, harmful_count,
    loaded_count, referenced_count, pinned, auto_inject, display_order) are copied
    from the specified episode to the new one. This supports edit flows where the
    old episode is deleted and recreated with new content while preserving feedback.
    """
    from graphiti_core.utils.datetime_utils import utc_now

    from app.services.memory.ingestion_config import LEARNING

    creator = get_episode_creator(scope=memory.scope, scope_id=memory.scope_id)
    result = await creator.create(
        content=request.content,
        name=f"{request.source.value}_{utc_now().isoformat()}",
        config=LEARNING,
        source_description=request.source_description,
        reference_time=request.reference_time,
        source=request.source,
    )
    if result.success:
        new_uuid = result.uuid or ""

        # Set injection tier if specified
        if request.injection_tier and new_uuid:
            from app.services.memory.graphiti_client import set_episode_injection_tier

            await set_episode_injection_tier(new_uuid, request.injection_tier.value)

        # Copy stats from source episode if requested
        if request.preserve_stats_from and new_uuid:
            from app.services.memory.graphiti_client import copy_episode_stats

            await copy_episode_stats(request.preserve_stats_from, new_uuid)

        return AddEpisodeResponse(uuid=new_uuid)
    else:
        raise HTTPException(
            status_code=500, detail=f"Failed to add episode: {result.validation_error}"
        )


@router.get("/list", response_model=MemoryListResult)
async def list_episodes(
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
    limit: Annotated[int, Query(ge=1, le=300, description="Max episodes per page")] = 50,
    cursor: Annotated[str | None, Query(description="Timestamp cursor for pagination")] = None,
    category: Annotated[MemoryCategory | None, Query(description="Filter by category")] = None,
) -> MemoryListResult:
    """
    List memory episodes with cursor-based pagination.

    Returns episodes in reverse chronological order (most recent first).
    Use the returned cursor to fetch the next page.
    """
    try:
        return await memory.list_episodes(
            limit=limit,
            cursor=cursor,
            category=category,
            all_groups=True,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list episodes: {e}") from e


@router.get("/stats", response_model=MemoryStats)
async def get_memory_stats(
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
) -> MemoryStats:
    """
    Get memory statistics across all groups.

    Returns total count, breakdown by category, and last updated time.
    The memory dashboard shows all episodes regardless of scope.
    """
    try:
        return await memory.get_stats(all_groups=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {e}") from e


@router.get("/scopes")
async def list_memory_scopes(
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
) -> Any:
    """
    List all memory scopes with episode counts.

    Returns scopes (global, project, task) with their episode counts.
    """
    try:
        return await memory.get_scope_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list scopes: {e}") from e


@router.get("/search", response_model=SearchResponse)
async def search_memory(
    query: Annotated[str, Query(..., description="Search query")],
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
    limit: Annotated[int, Query(ge=1, le=300, description="Max results")] = 10,
    min_score: Annotated[float, Query(ge=0.0, le=1.0, description="Minimum relevance score")] = 0.0,
) -> SearchResponse:
    """
    Semantic search for relevant episodes and facts.

    Uses semantic/vector search for agent tools that need
    relevance-based retrieval from the knowledge graph.
    """
    try:
        results = await memory.search(
            query=query,
            limit=limit,
            min_score=min_score,
            all_groups=True,
        )
        return SearchResponse(
            query=query,
            results=results,
            count=len(results),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {e}") from e


@router.get("/text-search", response_model=MemoryListResult)
async def text_search_memory(
    query: Annotated[str, Query(..., min_length=1, description="Text search query")],
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
    limit: Annotated[int, Query(ge=1, le=300, description="Max results")] = 50,
    category: Annotated[MemoryCategory | None, Query(description="Filter by category")] = None,
) -> MemoryListResult:
    """
    Text-based search for episode management UI.

    Simple case-insensitive substring search on content, name, summary, and tier.
    Does not use semantic/vector search - designed for human management.
    """
    try:
        episodes = await memory.text_search(
            query=query,
            limit=limit,
            category=category,
            all_groups=True,
        )
        return MemoryListResult(
            episodes=episodes,
            total=len(episodes),
            cursor=None,
            has_more=False,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Text search failed: {e}") from e


@router.get("/episode/{episode_id}", response_model=EpisodeDetailResponse)
async def get_episode(
    full_uuid: Annotated[str, Depends(resolve_episode_uuid)],
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
) -> EpisodeDetailResponse:
    """
    Get detailed information about a single episode.

    Accepts either a full UUID or an 8-character prefix.

    Returns episode content, metadata, and Neo4j usage statistics
    including helpful/harmful counts for ACE feedback tracking.
    """
    result = await memory.get_episode(full_uuid)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Episode {full_uuid} not found")
    return EpisodeDetailResponse(**result)


@router.delete("/episode/{episode_id}", response_model=DeleteEpisodeResponse)
async def delete_episode(
    full_uuid: Annotated[str, Depends(resolve_episode_uuid)],
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
) -> DeleteEpisodeResponse:
    """
    Delete an episode from memory.

    Accepts either a full UUID or an 8-character prefix.

    Removes the episode and cleans up orphaned entities/edges
    that were only connected through this episode.
    """
    try:
        await memory.delete_episode(full_uuid)
        return DeleteEpisodeResponse(
            success=True,
            episode_id=full_uuid,
            message="Episode deleted successfully",
        )
    except Exception as e:
        raise HTTPException(
            status_code=404 if "not found" in str(e).lower() else 500,
            detail=f"Failed to delete episode: {e}",
        ) from e


@router.patch("/episode/{episode_id}/properties", response_model=UpdateEpisodePropertiesResponse)
async def update_episode_properties(
    full_uuid: Annotated[str, Depends(resolve_episode_uuid)],
    request: UpdateEpisodePropertiesRequest,
) -> UpdateEpisodePropertiesResponse:
    """
    Update episode properties (pinned, auto_inject, display_order, trigger_task_types, trigger_phases, summary).

    - pinned=true: Episode will never be demoted by tier_optimizer
    - auto_inject=true: Reference-tier episode will be injected like mandates/guardrails
    - display_order: Controls injection order within tier (1-99, lower = earlier)
    - trigger_task_types: Task types that auto-inject this reference (e.g., ["database"])
    - trigger_phases: Subtask phases that auto-inject this reference (e.g., ["backend"])
    - summary: Short summary for TOON reference index (~20 chars)

    Accepts either a full UUID or an 8-character prefix.
    """
    from app.services.memory.graphiti_client import (
        set_episode_auto_inject,
        set_episode_display_order,
        set_episode_pinned,
        set_episode_summary,
        set_episode_trigger_phases,
        set_episode_trigger_task_types,
    )

    try:
        messages = []
        final_pinned = None
        final_auto_inject = None
        final_display_order = None
        final_trigger_task_types = None
        final_trigger_phases = None

        if request.pinned is not None:
            success = await set_episode_pinned(full_uuid, request.pinned)
            if not success:
                raise HTTPException(status_code=404, detail=f"Episode {full_uuid} not found")
            final_pinned = request.pinned
            messages.append(f"pinned={request.pinned}")

        if request.auto_inject is not None:
            success = await set_episode_auto_inject(full_uuid, request.auto_inject)
            if not success:
                raise HTTPException(status_code=404, detail=f"Episode {full_uuid} not found")
            final_auto_inject = request.auto_inject
            messages.append(f"auto_inject={request.auto_inject}")

        if request.display_order is not None:
            success = await set_episode_display_order(full_uuid, request.display_order)
            if not success:
                raise HTTPException(status_code=404, detail=f"Episode {full_uuid} not found")
            final_display_order = request.display_order
            messages.append(f"display_order={request.display_order}")

        if request.trigger_task_types is not None:
            success = await set_episode_trigger_task_types(full_uuid, request.trigger_task_types)
            if not success:
                raise HTTPException(status_code=404, detail=f"Episode {full_uuid} not found")
            final_trigger_task_types = request.trigger_task_types
            messages.append(f"trigger_task_types={request.trigger_task_types}")

        if request.trigger_phases is not None:
            success = await set_episode_trigger_phases(full_uuid, request.trigger_phases)
            if not success:
                raise HTTPException(status_code=404, detail=f"Episode {full_uuid} not found")
            final_trigger_phases = request.trigger_phases
            messages.append(f"trigger_phases={request.trigger_phases}")

        final_summary = None
        if request.summary is not None:
            success = await set_episode_summary(full_uuid, request.summary)
            if not success:
                raise HTTPException(status_code=404, detail=f"Episode {full_uuid} not found")
            final_summary = request.summary
            messages.append(f"summary={request.summary}")

        if not messages:
            raise HTTPException(status_code=400, detail="No properties to update")

        return UpdateEpisodePropertiesResponse(
            success=True,
            episode_id=full_uuid,
            pinned=final_pinned,
            auto_inject=final_auto_inject,
            display_order=final_display_order,
            trigger_task_types=final_trigger_task_types,
            trigger_phases=final_trigger_phases,
            summary=final_summary,
            message=f"Updated: {', '.join(messages)}",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update properties: {e}") from e


@router.get("/episode/{episode_id}/citations")
async def get_episode_citations(
    full_uuid: Annotated[str, Depends(resolve_episode_uuid)],
    limit: Annotated[int, Query(ge=1, le=100, description="Max citations")] = 20,
) -> Any:
    """
    Get injection sessions where this episode was cited.

    Queries MemoryInjectionMetric for sessions that cited this episode UUID.
    """
    import json

    from sqlalchemy import select, text

    from app.db import _get_session_factory
    from app.models import MemoryInjectionMetric

    session_factory = _get_session_factory()
    try:
        async with session_factory() as session:
            stmt = (
                select(MemoryInjectionMetric)
                .where(text("CAST(memories_cited AS jsonb) @> CAST(:cited AS jsonb)"))
                .order_by(MemoryInjectionMetric.created_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt, {"cited": json.dumps([full_uuid])})
            records = result.scalars().all()

        return {
            "episode_uuid": full_uuid,
            "citations": [
                {
                    "session_id": r.session_id,
                    "project_id": r.project_id,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "variant": r.variant or "BASELINE",
                }
                for r in records
            ],
            "total": len(records),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get citations: {e}") from e


@router.get("/episode/{episode_id}/similar")
async def get_similar_episodes(
    full_uuid: Annotated[str, Depends(resolve_episode_uuid)],
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
    limit: Annotated[int, Query(ge=1, le=20, description="Max similar episodes")] = 5,
    min_score: Annotated[float, Query(ge=0.0, le=1.0, description="Min similarity")] = 0.7,
) -> Any:
    """
    Find episodes with similar content via embedding search.

    Uses Graphiti's semantic search with the episode's content as query.
    """
    episode = await memory.get_episode(full_uuid)
    if not episode:
        raise HTTPException(status_code=404, detail=f"Episode {full_uuid} not found")

    try:
        results = await memory.search(
            query=episode["content"],
            limit=limit + 1,
            min_score=min_score,
            all_groups=True,
        )
        similar = [
            {
                "uuid": r.uuid,
                "content": r.content[:200],
                "relevance_score": round(r.relevance_score, 3),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in results
            if r.uuid != full_uuid
        ][:limit]

        return {
            "episode_uuid": full_uuid,
            "similar": similar,
            "total": len(similar),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to find similar episodes: {e}") from e


@router.get("/health", response_model=HealthResponse)
async def memory_health(
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
) -> HealthResponse:
    """
    Check memory system health.

    Returns connection status for Neo4j and the knowledge graph.
    """
    health = await memory.health_check()
    return HealthResponse(**health)
