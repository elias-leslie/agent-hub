"""Memory API - Knowledge graph memory management."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from starlette.responses import StreamingResponse

from app.services.memory import MemoryService, get_memory_service

# Observation capture schemas and handler
from app.services.memory.capture_handler import capture_observation
from app.services.memory.episode_creator import get_episode_creator
from app.services.memory.memory_models import MemoryScopeCount
from app.services.memory.memory_utils import resolve_uuid_prefix
from app.services.memory.observation_schema import ObservationRequest, ObservationResponse
from app.services.memory.service import (
    MemoryCategory,
    MemoryListResult,
    MemoryScope,
    MemoryStats,
)

from .memory_agent_tools import router as agent_tools_router
from .memory_bulk_ops import router as bulk_ops_router
from .memory_metrics import router as metrics_router
from .memory_rating import router as rating_router
from .memory_schemas import (
    AddEpisodeRequest,
    AddEpisodeResponse,
    DeleteEpisodeResponse,
    EpisodeDetailResponse,
    HealthResponse,
    PhaseTriggeredReferencesResponse,
    SearchResponse,
    TriggeredReferenceItem,
    TriggeredReferencesResponse,
    UpdateEpisodePropertiesRequest,
    UpdateEpisodePropertiesResponse,
)
from .memory_settings import router as settings_router

# Create main router
router = APIRouter(prefix="/memory", tags=["memory"])


def get_scope_params(
    x_memory_scope: Annotated[str | None, Header()] = None,
    x_scope_id: Annotated[str | None, Header()] = None,
) -> tuple[MemoryScope, str | None]:
    """Get scope parameters from headers or use defaults."""
    scope = MemoryScope.GLOBAL
    if x_memory_scope:
        scope_value = x_memory_scope.lower()
        valid_scopes = [s.value for s in MemoryScope]
        if scope_value in valid_scopes:
            scope = MemoryScope(scope_value)
    return scope, x_scope_id


def get_memory_svc(
    scope_params: Annotated[tuple[MemoryScope, str | None], Depends(get_scope_params)],
) -> MemoryService:
    """Get memory service instance for the scope."""
    scope, scope_id = scope_params
    return get_memory_service(scope, scope_id)


# Include sub-routers

router.include_router(settings_router)
router.include_router(agent_tools_router, tags=["agent-tools"])
router.include_router(rating_router, tags=["agent-tools"])
router.include_router(metrics_router, tags=["metrics"])
router.include_router(bulk_ops_router)


# ============================================================================
# Triggered References Endpoint
# ============================================================================


@router.get("/triggered-references", response_model=TriggeredReferencesResponse)
async def get_triggered_references_endpoint(
    task_type: Annotated[
        str, Query(..., description="Task type to match against trigger_task_types")
    ],
) -> TriggeredReferencesResponse:
    """
    Get reference episodes triggered by a specific task_type.

    Returns reference-tier episodes where the task_type is in their trigger_task_types.
    Used for context-aware reference injection in st work and autonomous execution.

    Example: GET /triggered-references?task_type=database
    Returns all references with "database" in their trigger_task_types.
    """
    from app.services.memory.graphiti_client import get_triggered_references

    try:
        refs = await get_triggered_references(task_type)
        return TriggeredReferencesResponse(
            task_type=task_type,
            references=[TriggeredReferenceItem(**r) for r in refs],
            count=len(refs),
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get triggered references: {e}",
        ) from e


@router.get("/phase-triggered-references", response_model="PhaseTriggeredReferencesResponse")
async def get_phase_triggered_references_endpoint(
    phase: Annotated[str, Query(..., description="Subtask phase to match against trigger_phases")],
) -> "PhaseTriggeredReferencesResponse":
    """
    Get reference episodes triggered by a specific subtask phase.

    Returns reference-tier episodes where the phase is in their trigger_phases.
    Used for context-aware reference injection in st context --subtask.

    Example: GET /phase-triggered-references?phase=backend
    Returns all references with "backend" in their trigger_phases.
    """
    from app.services.memory.graphiti_client import get_phase_triggered_references

    from .memory_schemas import PhaseTriggeredReferenceItem, PhaseTriggeredReferencesResponse

    try:
        refs = await get_phase_triggered_references(phase)
        return PhaseTriggeredReferencesResponse(
            phase=phase,
            references=[PhaseTriggeredReferenceItem(**r) for r in refs],
            count=len(refs),
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get phase triggered references: {e}",
        ) from e


# ============================================================================
# Observation Capture Endpoint
# ============================================================================


@router.post("/observations", response_model=ObservationResponse)
async def capture_observation_endpoint(
    request: ObservationRequest,
    scope_params: Annotated[tuple[MemoryScope, str | None], Depends(get_scope_params)],
) -> ObservationResponse:
    """
    Capture an observation and store it as a Graphiti episode.

    Observations from various sources (Claude Code, agent chat, tasks) are
    converted into episodes with appropriate ingestion profiles and privacy
    filtering. Content wrapped in <private> tags is redacted; <memory> tags
    are stripped to prevent recursive storage.
    """
    scope, scope_id = scope_params
    try:
        return await capture_observation(request, scope, scope_id)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to capture observation: {e}",
        ) from e


# ============================================================================
# Dashboard Tab Endpoints
# ============================================================================


@router.get("/timeline")
async def get_timeline(
    scope_params: Annotated[tuple[MemoryScope, str | None], Depends(get_scope_params)],
    category: Annotated[MemoryCategory | None, Query(description="Filter by category")] = None,
    limit: Annotated[int, Query(ge=1, le=500, description="Max episodes")] = 200,
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
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get timeline: {e}",
        ) from e


@router.get("/sessions-with-memory")
async def get_sessions_with_memory_endpoint(
    limit: Annotated[int, Query(ge=1, le=100, description="Max sessions per page")] = 50,
    offset: Annotated[int, Query(ge=0, description="Offset for pagination")] = 0,
) -> Any:
    from app.services.memory.session_memory_service import get_sessions_with_memory

    try:
        return await get_sessions_with_memory(limit=limit, offset=offset)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get sessions: {e}",
        ) from e


@router.get("/analytics")
async def get_analytics(
    group_id: Annotated[
        str | None,
        Query(description="Filter by group_id"),
    ] = None,
    days: Annotated[int, Query(ge=1, le=90, description="Days to look back for trend")] = 30,
) -> Any:
    from app.services.memory.analytics_service import get_memory_analytics

    try:
        return await get_memory_analytics(group_id=group_id, days=days)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get analytics: {e}",
        ) from e


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
async def summarize_session(session_id: str) -> Any:
    from app.services.memory.summary_generator import generate_session_summary

    try:
        return await generate_session_summary(session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate summary: {e}",
        ) from e


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
        raise HTTPException(
            status_code=500,
            detail=f"Failed to build continuity context: {e}",
        ) from e


# ============================================================================
# Episode CRUD Endpoints
# ============================================================================


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
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list episodes: {e}") from e


@router.get("/stats", response_model=MemoryStats)
async def get_memory_stats(
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
) -> MemoryStats:
    """
    Get memory statistics for the current group.

    Returns total count, breakdown by category, and last updated time.
    """
    try:
        return await memory.get_stats()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {e}") from e


@router.get("/scopes", response_model=list[MemoryScopeCount])
async def list_memory_scopes(
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
) -> list[MemoryScopeCount]:
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
    episode_id: str,
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
) -> EpisodeDetailResponse:
    """
    Get detailed information about a single episode.

    Accepts either a full UUID or an 8-character prefix.

    Returns episode content, metadata, and Neo4j usage statistics
    including helpful/harmful counts for ACE feedback tracking.
    """
    try:
        # Resolve UUID prefix to full UUID if needed
        full_uuid = await resolve_uuid_prefix(episode_id, group_id="global")
        result = await memory.get_episode(full_uuid)
        if result is None:
            raise HTTPException(status_code=404, detail=f"Episode {episode_id} not found")
        return EpisodeDetailResponse(**result)
    except ValueError as e:
        # Prefix resolution errors (ambiguous, not found)
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.delete("/episode/{episode_id}", response_model=DeleteEpisodeResponse)
async def delete_episode(
    episode_id: str,
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
) -> DeleteEpisodeResponse:
    """
    Delete an episode from memory.

    Accepts either a full UUID or an 8-character prefix.

    Removes the episode and cleans up orphaned entities/edges
    that were only connected through this episode.
    """
    try:
        # Resolve UUID prefix to full UUID if needed
        full_uuid = await resolve_uuid_prefix(episode_id, group_id="global")
        await memory.delete_episode(full_uuid)
        return DeleteEpisodeResponse(
            success=True,
            episode_id=full_uuid,
            message="Episode deleted successfully",
        )
    except ValueError as e:
        # Prefix resolution errors (ambiguous, not found)
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=404 if "not found" in str(e).lower() else 500,
            detail=f"Failed to delete episode: {e}",
        ) from e


@router.patch("/episode/{episode_id}/properties", response_model=UpdateEpisodePropertiesResponse)
async def update_episode_properties(
    episode_id: str,
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
        full_uuid = await resolve_uuid_prefix(episode_id, group_id="global")

        messages = []
        final_pinned = None
        final_auto_inject = None
        final_display_order = None
        final_trigger_task_types = None
        final_trigger_phases = None

        if request.pinned is not None:
            success = await set_episode_pinned(full_uuid, request.pinned)
            if not success:
                raise HTTPException(status_code=404, detail=f"Episode {episode_id} not found")
            final_pinned = request.pinned
            messages.append(f"pinned={request.pinned}")

        if request.auto_inject is not None:
            success = await set_episode_auto_inject(full_uuid, request.auto_inject)
            if not success:
                raise HTTPException(status_code=404, detail=f"Episode {episode_id} not found")
            final_auto_inject = request.auto_inject
            messages.append(f"auto_inject={request.auto_inject}")

        if request.display_order is not None:
            success = await set_episode_display_order(full_uuid, request.display_order)
            if not success:
                raise HTTPException(status_code=404, detail=f"Episode {episode_id} not found")
            final_display_order = request.display_order
            messages.append(f"display_order={request.display_order}")

        if request.trigger_task_types is not None:
            success = await set_episode_trigger_task_types(full_uuid, request.trigger_task_types)
            if not success:
                raise HTTPException(status_code=404, detail=f"Episode {episode_id} not found")
            final_trigger_task_types = request.trigger_task_types
            messages.append(f"trigger_task_types={request.trigger_task_types}")

        if request.trigger_phases is not None:
            success = await set_episode_trigger_phases(full_uuid, request.trigger_phases)
            if not success:
                raise HTTPException(status_code=404, detail=f"Episode {episode_id} not found")
            final_trigger_phases = request.trigger_phases
            messages.append(f"trigger_phases={request.trigger_phases}")

        final_summary = None
        if request.summary is not None:
            success = await set_episode_summary(full_uuid, request.summary)
            if not success:
                raise HTTPException(status_code=404, detail=f"Episode {episode_id} not found")
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
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update properties: {e}") from e


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
