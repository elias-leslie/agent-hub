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
    """Add an episode to the knowledge graph. Optionally set tier and preserve stats."""
    return await handle_add_episode(request, memory)


@router.get("/list", response_model=MemoryListResult)
async def list_episodes(
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
    limit: Annotated[int, Query(ge=1, le=300, description="Max episodes per page")] = 50,
    cursor: Annotated[str | None, Query(description="Timestamp cursor for pagination")] = None,
    category: Annotated[MemoryCategory | None, Query(description="Filter by category")] = None,
) -> MemoryListResult:
    """List episodes with cursor-based pagination (reverse chronological order)."""
    return await handle_list_episodes(memory, limit, cursor, category)


@router.get("/stats", response_model=MemoryStats)
async def get_memory_stats(
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
) -> MemoryStats:
    """Get memory statistics across all groups (total count, category breakdown, last updated)."""
    return await handle_get_memory_stats(memory)


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
) -> SearchResponse:
    """Semantic/vector search for relevant episodes and facts."""
    return await handle_search_memory(query, memory, limit, min_score)


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
) -> DeleteEpisodeResponse:
    """Delete episode and clean up orphaned entities/edges. Accepts UUID or 8-char prefix."""
    return await handle_delete_episode(full_uuid, memory)


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
    """Check memory system health (Neo4j and knowledge graph connection status)."""
    return await handle_memory_health(memory)
