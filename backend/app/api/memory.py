"""Memory API - Knowledge graph memory management."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.memory import MemoryService, get_memory_service
from app.services.memory.consolidation import (
    ConsolidationRequest,
    ConsolidationResult,
    consolidate_task_memories,
)
from app.services.memory.learning_extractor import (
    ExtractionResult,
    ExtractLearningsRequest,
    extract_learnings,
)
from app.services.memory.promotion import (
    PromoteRequest,
    PromotionResult,
    get_canonical_context,
    promote_learning,
)
from app.services.memory.service import (
    MemoryCategory,
    MemoryContext,
    MemoryListResult,
    MemoryScope,
    MemoryScopeCount,
    MemorySearchResult,
    MemorySource,
    MemoryStats,
)
from app.services.memory.tools import (
    RecordDiscoveryRequest,
    RecordGotchaRequest,
    RecordPatternRequest,
    RecordResponse,
    SessionContextResponse,
    get_session_context,
    record_discovery,
    record_gotcha,
    record_pattern,
)

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


# Request/Response schemas
class AddEpisodeRequest(BaseModel):
    """Request body for adding an episode to memory."""

    content: str = Field(..., description="Content to remember")
    source: MemorySource = Field(MemorySource.CHAT, description="Source type (chat, voice, system)")
    source_description: str | None = Field(None, description="Human-readable source description")
    reference_time: datetime | None = Field(
        None, description="When the episode occurred (defaults to now)"
    )


class AddEpisodeResponse(BaseModel):
    """Response body for add episode."""

    uuid: str = Field(..., description="UUID of the created episode")
    message: str = Field(default="Episode added successfully")


class SearchResponse(BaseModel):
    """Response body for memory search."""

    query: str
    results: list[MemorySearchResult]
    count: int


class ContextResponse(BaseModel):
    """Response body for context retrieval."""

    context: MemoryContext
    formatted: str = Field(..., description="Pre-formatted context string for LLM injection")


class HealthResponse(BaseModel):
    """Response body for health check."""

    status: str
    neo4j: str
    scope: str | None = None
    scope_id: str | None = None
    error: str | None = None


@router.post("/add", response_model=AddEpisodeResponse)
async def add_episode(
    request: AddEpisodeRequest,
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
) -> AddEpisodeResponse:
    """
    Add an episode to the knowledge graph memory.

    Episodes are processed to extract entities and relationships,
    which are stored in the knowledge graph for semantic retrieval.
    """
    try:
        uuid = await memory.add_episode(
            content=request.content,
            source=request.source,
            source_description=request.source_description,
            reference_time=request.reference_time,
        )
        return AddEpisodeResponse(uuid=uuid)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add episode: {e}") from e


@router.get("/list", response_model=MemoryListResult)
async def list_episodes(
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
    limit: Annotated[int, Query(ge=1, le=100, description="Max episodes per page")] = 50,
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
    limit: Annotated[int, Query(ge=1, le=100, description="Max results")] = 10,
    min_score: Annotated[float, Query(ge=0.0, le=1.0, description="Minimum relevance score")] = 0.0,
) -> SearchResponse:
    """
    Search memory for relevant episodes and facts.

    Uses semantic search combined with graph traversal to find
    relevant information from the knowledge graph.
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


@router.get("/context", response_model=ContextResponse)
async def get_context(
    query: Annotated[str, Query(..., description="Query to find context for")],
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
    max_facts: Annotated[int, Query(ge=1, le=50, description="Maximum facts to include")] = 10,
    max_entities: Annotated[int, Query(ge=1, le=20, description="Maximum entities to include")] = 5,
) -> ContextResponse:
    """
    Get relevant context for a query, formatted for LLM injection.

    Returns facts and entities relevant to the query, along with
    a pre-formatted string suitable for system prompt injection.
    """
    try:
        context = await memory.get_context_for_query(
            query=query,
            max_facts=max_facts,
            max_entities=max_entities,
        )

        # Format context for LLM injection
        formatted_parts = []
        if context.relevant_facts:
            formatted_parts.append("Relevant facts from memory:")
            for fact in context.relevant_facts:
                formatted_parts.append(f"- {fact}")

        if context.relevant_entities:
            formatted_parts.append("\nKnown entities:")
            for entity in context.relevant_entities:
                formatted_parts.append(f"- {entity}")

        formatted = "\n".join(formatted_parts) if formatted_parts else ""

        return ContextResponse(context=context, formatted=formatted)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Context retrieval failed: {e}") from e


class DeleteEpisodeResponse(BaseModel):
    """Response body for episode deletion."""

    success: bool
    episode_id: str
    message: str


@router.delete("/episode/{episode_id}", response_model=DeleteEpisodeResponse)
async def delete_episode(
    episode_id: str,
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
) -> DeleteEpisodeResponse:
    """
    Delete an episode from memory.

    Removes the episode and cleans up orphaned entities/edges
    that were only connected through this episode.
    """
    try:
        await memory.delete_episode(episode_id)
        return DeleteEpisodeResponse(
            success=True,
            episode_id=episode_id,
            message="Episode deleted successfully",
        )
    except Exception as e:
        raise HTTPException(
            status_code=404 if "not found" in str(e).lower() else 500,
            detail=f"Failed to delete episode: {e}",
        ) from e


class BulkDeleteRequest(BaseModel):
    """Request body for bulk episode deletion."""

    ids: list[str] = Field(..., min_length=1, description="Episode UUIDs to delete")


class BulkDeleteError(BaseModel):
    """Error detail for a single failed deletion."""

    id: str
    error: str


class BulkDeleteResponse(BaseModel):
    """Response body for bulk deletion."""

    deleted: int = Field(..., description="Number of successfully deleted episodes")
    failed: int = Field(..., description="Number of failed deletions")
    errors: list[BulkDeleteError] = Field(default_factory=list, description="Error details")


@router.post("/bulk-delete", response_model=BulkDeleteResponse)
async def bulk_delete_episodes(
    request: BulkDeleteRequest,
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
) -> BulkDeleteResponse:
    """
    Delete multiple episodes from memory.

    Attempts to delete all provided episode IDs.
    Returns counts of successful and failed deletions.
    """
    try:
        result = await memory.bulk_delete(request.ids)
        return BulkDeleteResponse(
            deleted=result["deleted"],
            failed=result["failed"],
            errors=[BulkDeleteError(**e) for e in result["errors"]],
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Bulk delete failed: {e}",
        ) from e


class CleanupResponse(BaseModel):
    """Response body for cleanup operation."""

    deleted: int
    skipped: bool
    reason: str | None = None


@router.post("/cleanup", response_model=CleanupResponse)
async def cleanup_stale_memories(
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
    ttl_days: Annotated[int, Query(ge=1, le=365, description="TTL in days")] = 30,
) -> CleanupResponse:
    """
    Clean up memories not accessed within TTL period.

    Has system activity safeguard: skips cleanup if system has been
    inactive for the same period to prevent accidental mass deletion.
    """
    try:
        result = await memory.cleanup_stale_memories(ttl_days=ttl_days)
        return CleanupResponse(**result)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Cleanup failed: {e}",
        ) from e


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


# Agent Tools Endpoints
# These endpoints are used by agents to record learnings during task execution


@router.post("/record-discovery", response_model=RecordResponse, tags=["agent-tools"])
async def api_record_discovery(request: RecordDiscoveryRequest) -> RecordResponse:
    """
    Record a codebase discovery for future reference.

    Used by agents to capture discoveries about the codebase during execution.
    These discoveries are stored for retrieval in future sessions.
    """
    try:
        return await record_discovery(request)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to record discovery: {e}",
        ) from e


@router.post("/record-gotcha", response_model=RecordResponse, tags=["agent-tools"])
async def api_record_gotcha(request: RecordGotchaRequest) -> RecordResponse:
    """
    Record a gotcha/pitfall for troubleshooting.

    Used by agents to capture gotchas and pitfalls encountered during execution.
    These are surfaced when similar issues might occur.
    """
    try:
        return await record_gotcha(request)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to record gotcha: {e}",
        ) from e


@router.post("/record-pattern", response_model=RecordResponse, tags=["agent-tools"])
async def api_record_pattern(request: RecordPatternRequest) -> RecordResponse:
    """
    Record a coding pattern for future reference.

    Used by agents to capture coding patterns discovered during execution.
    These patterns are surfaced when working on similar code.
    """
    try:
        return await record_pattern(request)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to record pattern: {e}",
        ) from e


@router.get("/session-context", response_model=SessionContextResponse, tags=["agent-tools"])
async def api_get_session_context(
    scope: Annotated[MemoryScope, Query(description="Memory scope")] = MemoryScope.PROJECT,
    scope_id: Annotated[str | None, Query(description="Project or task ID")] = None,
    num_results: Annotated[int, Query(ge=1, le=50, description="Max results per category")] = 10,
) -> SessionContextResponse:
    """
    Get accumulated learnings from previous sessions.

    Returns discoveries, gotchas, and patterns that may be relevant
    for the current session based on the specified scope.
    """
    try:
        return await get_session_context(
            scope=scope,
            scope_id=scope_id,
            num_results=num_results,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get session context: {e}",
        ) from e


@router.post("/consolidate", response_model=ConsolidationResult, tags=["agent-tools"])
async def api_consolidate_task_memories(request: ConsolidationRequest) -> ConsolidationResult:
    """
    Consolidate memories after task completion.

    Called when a task completes to:
    - On success: Promote valuable task memories to project scope
    - On failure: Clean up ephemeral memories while preserving troubleshooting guides

    This endpoint is typically called by the task orchestration system
    when a task transitions to completed or failed state.
    """
    try:
        return await consolidate_task_memories(request)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to consolidate memories: {e}",
        ) from e


@router.post("/extract-learnings", response_model=ExtractionResult, tags=["agent-tools"])
async def api_extract_learnings(request: ExtractLearningsRequest) -> ExtractionResult:
    """
    Extract learnings from a Claude Code session transcript.

    Uses LLM analysis to identify:
    - Verified learnings (user confirmed, 95% confidence)
    - Inference learnings (from successful outcomes, 80% confidence)
    - Pattern learnings (observed behaviors, 60% confidence)

    Learnings are stored with status based on confidence:
    - 70-89%: provisional (needs reinforcement to promote)
    - 90+%: canonical (immediately trusted)

    This endpoint is typically called by session end hooks to capture
    learnings for cross-session knowledge transfer.
    """
    try:
        return await extract_learnings(request)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to extract learnings: {e}",
        ) from e


@router.post("/promote", response_model=PromotionResult, tags=["agent-tools"])
async def api_promote_learning(request: PromoteRequest) -> PromotionResult:
    """
    Manually promote a learning from provisional to canonical status.

    Used when a learning has been verified manually or through
    external validation (e.g., code review, user feedback).

    Note: Automatic promotion happens through reinforcement when
    the same learning is extracted multiple times across sessions.
    """
    try:
        return await promote_learning(request)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to promote learning: {e}",
        ) from e


class CanonicalContextRequest(BaseModel):
    """Request for canonical context retrieval."""

    query: str = Field(..., description="Query to find relevant context")
    max_facts: int = Field(10, ge=1, le=50, description="Maximum facts to return")
    include_provisional: bool = Field(
        False, description="Whether to include provisional learnings"
    )


class CanonicalContextResponse(BaseModel):
    """Response with canonical context."""

    facts: list[str]
    count: int


@router.post("/canonical-context", response_model=CanonicalContextResponse, tags=["agent-tools"])
async def api_get_canonical_context(request: CanonicalContextRequest) -> CanonicalContextResponse:
    """
    Get context from canonical learnings (trusted knowledge).

    By default only returns canonical (90+ confidence) learnings.
    Set include_provisional=true to also include provisional learnings.

    This is the preferred endpoint for injecting context into sessions,
    as it filters out low-confidence learnings that may not be reliable.
    """
    try:
        facts = await get_canonical_context(
            query=request.query,
            max_facts=request.max_facts,
            include_provisional=request.include_provisional,
        )
        return CanonicalContextResponse(facts=facts, count=len(facts))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get canonical context: {e}",
        ) from e
