"""Memory API - Knowledge graph memory management."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.memory import MemoryService, get_memory_service
from app.services.memory.golden_standards import (
    list_golden_standards,
    mark_as_golden_standard,
    seed_golden_standards,
    store_golden_standard,
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


class ProgressiveContextBlock(BaseModel):
    """A single block of progressive context."""

    items: list[str] = Field(..., description="List of memory items in this block")
    count: int = Field(..., description="Number of items")


class ScoringBreakdown(BaseModel):
    """Scoring breakdown for a single memory item."""

    uuid: str = Field(..., description="Memory UUID (first 8 chars)")
    score: float = Field(..., description="Final score after multipliers")
    semantic: float = Field(..., description="Semantic similarity component")
    content_preview: str = Field(..., description="First 60 chars of content")


class ProgressiveContextResponse(BaseModel):
    """Response with 3-block progressive disclosure context."""

    mandates: ProgressiveContextBlock = Field(..., description="Always-inject golden standards")
    guardrails: ProgressiveContextBlock = Field(..., description="Type-filtered anti-patterns")
    reference: ProgressiveContextBlock = Field(..., description="Semantic search patterns")
    total_tokens: int = Field(..., description="Estimated total tokens")
    formatted: str = Field(..., description="Pre-formatted context for injection")
    variant: str = Field(..., description="A/B variant used for this request")
    debug: dict | None = Field(None, description="Debug info when debug=True")
    scoring_breakdown: list[ScoringBreakdown] | None = Field(
        None, description="Scoring breakdown when debug=True"
    )


@router.get("/progressive-context", response_model=ProgressiveContextResponse, tags=["agent-tools"])
async def get_progressive_context(
    query: Annotated[str, Query(..., description="Query to find relevant context")],
    scope_params: Annotated[tuple[MemoryScope, str | None], Depends(get_scope_params)],
    debug: Annotated[bool, Query(description="Include debug info")] = False,
    include_global: Annotated[
        bool,
        Query(description="Include global scope when querying project scope (default True)"),
    ] = True,
    variant: Annotated[
        str | None,
        Query(description="A/B variant override (BASELINE, ENHANCED, MINIMAL, AGGRESSIVE)"),
    ] = None,
    external_id: Annotated[
        str | None,
        Query(description="External ID for deterministic variant assignment"),
    ] = None,
    project_id: Annotated[
        str | None,
        Query(description="Project ID for deterministic variant assignment"),
    ] = None,
) -> ProgressiveContextResponse:
    """
    Get 3-block progressive disclosure context for a query.

    Returns context in three blocks:
    - **Mandates**: Golden standards (confidence=100) - always injected
    - **Guardrails**: Anti-patterns and gotchas (TROUBLESHOOTING_GUIDE)
    - **Reference**: Patterns and workflows (CODING_STANDARD, OPERATIONAL_CONTEXT)

    This endpoint is designed for SessionStart hooks to efficiently
    retrieve relevant context with minimal token usage (~150-200 tokens).

    **A/B Testing:**
    - Pass `variant` to override variant assignment for testing
    - Pass `external_id` and `project_id` for deterministic hash-based assignment
    - Response includes `variant` field showing which variant was used

    When scope is PROJECT and include_global=True (default), results from both
    the project scope AND global scope are merged and returned.
    """
    from app.services.memory.context_injector import (
        ProgressiveContext,
        build_progressive_context,
        format_progressive_context,
        get_relevance_debug_info,
    )
    from app.services.memory.variants import assign_variant

    scope, scope_id = scope_params

    # Determine variant (override or hash-based assignment)
    assigned_variant = assign_variant(
        external_id=external_id,
        project_id=project_id or scope_id,
        variant_override=variant,
    )

    # Build progressive context (includes global when scope=PROJECT and include_global=True)
    context: ProgressiveContext = await build_progressive_context(
        query=query,
        scope=scope,
        scope_id=scope_id,
        include_global=include_global,
    )

    # Store variant in debug info for downstream use
    context.debug_info["variant"] = assigned_variant.value

    # Format for injection
    formatted = format_progressive_context(context)

    # Build scoring breakdown if debug=True
    scoring_breakdown: list[ScoringBreakdown] | None = None
    if debug:
        scoring_breakdown = []
        for m in context.mandates:
            scoring_breakdown.append(
                ScoringBreakdown(
                    uuid=m.uuid[:8] if m.uuid else "unknown",
                    score=m.relevance_score,
                    semantic=m.relevance_score,  # Golden standards have fixed 1.0 relevance
                    content_preview=m.content[:60] + "..." if len(m.content) > 60 else m.content,
                )
            )
        for g in context.guardrails:
            scoring_breakdown.append(
                ScoringBreakdown(
                    uuid=g.uuid[:8] if g.uuid else "unknown",
                    score=g.relevance_score,
                    semantic=g.relevance_score,
                    content_preview=g.content[:60] + "..." if len(g.content) > 60 else g.content,
                )
            )
        for r in context.reference:
            scoring_breakdown.append(
                ScoringBreakdown(
                    uuid=r.uuid[:8] if r.uuid else "unknown",
                    score=r.relevance_score,
                    semantic=r.relevance_score,
                    content_preview=r.content[:60] + "..." if len(r.content) > 60 else r.content,
                )
            )

    # Build response
    response = ProgressiveContextResponse(
        mandates=ProgressiveContextBlock(
            items=[m.content for m in context.mandates],
            count=len(context.mandates),
        ),
        guardrails=ProgressiveContextBlock(
            items=[g.content for g in context.guardrails],
            count=len(context.guardrails),
        ),
        reference=ProgressiveContextBlock(
            items=[r.content for r in context.reference],
            count=len(context.reference),
        ),
        total_tokens=context.total_tokens,
        formatted=formatted,
        variant=assigned_variant.value,
        debug=get_relevance_debug_info(context) if debug else None,
        scoring_breakdown=scoring_breakdown,
    )

    return response


class CanonicalContextRequest(BaseModel):
    """Request for canonical context retrieval."""

    query: str = Field(..., description="Query to find relevant context")
    max_facts: int = Field(10, ge=1, le=50, description="Maximum facts to return")
    include_provisional: bool = Field(False, description="Whether to include provisional learnings")


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


# Golden Standards Endpoints


class StoreGoldenStandardRequest(BaseModel):
    """Request to store a golden standard."""

    content: str = Field(..., description="Golden standard content")
    category: MemoryCategory = Field(..., description="Memory category")
    title: str | None = Field(None, description="Optional title")


class GoldenStandardResponse(BaseModel):
    """Response for golden standard operations."""

    uuid: str | None = None
    success: bool
    message: str


class GoldenStandardItem(BaseModel):
    """A golden standard item."""

    uuid: str
    name: str
    content: str
    source_description: str
    created_at: str
    loaded_count: int = 0
    referenced_count: int = 0
    success_count: int = 0
    utility_score: float = 0.5


class ListGoldenStandardsResponse(BaseModel):
    """Response for listing golden standards."""

    items: list[GoldenStandardItem]
    count: int


@router.post("/golden-standards", response_model=GoldenStandardResponse, tags=["golden-standards"])
async def api_store_golden_standard(
    request: StoreGoldenStandardRequest,
    scope_params: Annotated[tuple[MemoryScope, str | None], Depends(get_scope_params)],
) -> GoldenStandardResponse:
    """
    Store a golden standard in the knowledge graph.

    Golden standards are curated, high-confidence knowledge that should
    always be injected when relevant. They have confidence=100 and are
    prioritized in the mandates block of progressive disclosure.
    """
    scope, scope_id = scope_params
    try:
        uuid = await store_golden_standard(
            content=request.content,
            category=request.category,
            title=request.title,
            scope=scope,
            scope_id=scope_id,
        )
        return GoldenStandardResponse(
            uuid=uuid,
            success=True,
            message="Golden standard stored successfully",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to store golden standard: {e}",
        ) from e


@router.get(
    "/golden-standards", response_model=ListGoldenStandardsResponse, tags=["golden-standards"]
)
async def api_list_golden_standards(
    scope_params: Annotated[tuple[MemoryScope, str | None], Depends(get_scope_params)],
    limit: Annotated[int, Query(ge=1, le=100, description="Max results")] = 50,
    sort_by: Annotated[
        str,
        Query(description="Sort by: utility_score (default), created_at, loaded_count"),
    ] = "utility_score",
) -> ListGoldenStandardsResponse:
    """
    List all golden standards in the knowledge graph.

    Returns golden standards with their metadata and usage stats for review and management.
    Supports sorting by utility_score (default), created_at, or loaded_count.
    """
    scope, scope_id = scope_params
    try:
        items = await list_golden_standards(
            scope=scope,
            scope_id=scope_id,
            limit=limit,
            sort_by=sort_by,
        )
        return ListGoldenStandardsResponse(
            items=[
                GoldenStandardItem(
                    uuid=item["uuid"],
                    name=item["name"],
                    content=item["content"],
                    source_description=item["source_description"],
                    created_at=str(item["created_at"]),
                    loaded_count=item.get("loaded_count", 0),
                    referenced_count=item.get("referenced_count", 0),
                    success_count=item.get("success_count", 0),
                    utility_score=item.get("utility_score", 0.5),
                )
                for item in items
            ],
            count=len(items),
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list golden standards: {e}",
        ) from e


@router.post(
    "/golden-standards/{episode_uuid}/mark",
    response_model=GoldenStandardResponse,
    tags=["golden-standards"],
)
async def api_mark_as_golden_standard(
    episode_uuid: str,
    scope_params: Annotated[tuple[MemoryScope, str | None], Depends(get_scope_params)],
) -> GoldenStandardResponse:
    """
    Mark an existing episode as a golden standard.

    Promotes an existing memory episode to golden standard status,
    setting confidence=100 and adding to the mandates block.
    """
    scope, scope_id = scope_params
    try:
        success = await mark_as_golden_standard(
            episode_uuid=episode_uuid,
            scope=scope,
            scope_id=scope_id,
        )
        return GoldenStandardResponse(
            uuid=episode_uuid if success else None,
            success=success,
            message="Marked as golden standard" if success else "Episode not found",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to mark as golden standard: {e}",
        ) from e


# save_learning Endpoint (for Claude to call via curl)


class SaveLearningRequest(BaseModel):
    """Request to save a learning from a session."""

    content: str = Field(..., description="The learning content")
    category: MemoryCategory = Field(
        MemoryCategory.CODING_STANDARD,
        description="Memory category (coding_standard, troubleshooting_guide, etc.)",
    )
    confidence: int = Field(
        80,
        ge=0,
        le=100,
        description="Confidence level (0-100). 70+ is provisional, 90+ is canonical.",
    )
    context: str | None = Field(None, description="Optional context about the learning source")


class SaveLearningResponse(BaseModel):
    """Response from save_learning endpoint."""

    uuid: str | None = Field(None, description="UUID of the created learning")
    status: str = Field(..., description="provisional or canonical based on confidence")
    is_duplicate: bool = Field(False, description="True if similar learning exists")
    reinforced_uuid: str | None = Field(
        None, description="UUID of reinforced learning if duplicate"
    )
    message: str


@router.post("/save-learning", response_model=SaveLearningResponse, tags=["agent-tools"])
async def api_save_learning(
    request: SaveLearningRequest,
    scope_params: Annotated[tuple[MemoryScope, str | None], Depends(get_scope_params)],
) -> SaveLearningResponse:
    """
    Save a learning from a Claude Code session.

    This endpoint allows Claude to save learnings discovered during a session.
    Learnings are stored with the provided confidence level and categorized
    as provisional (70-89%) or canonical (90+%).

    Duplicate detection: If a semantically similar learning exists, the existing
    learning is reinforced instead of creating a duplicate.

    **Claude can call this via curl:**
    ```bash
    curl -X POST http://localhost:8003/api/memory/save-learning \\
      -H "Content-Type: application/json" \\
      -d '{"content": "Always use async methods for DB operations", "category": "coding_standard"}'
    ```
    """
    from app.services.memory.episode_formatter import (
        EpisodeOrigin,
        EpisodeValidationError,
        InjectionTier,
        get_episode_formatter,
    )
    from app.services.memory.learning_extractor import (
        CANONICAL_THRESHOLD,
        PROVISIONAL_THRESHOLD,
        LearningStatus,
    )
    from app.services.memory.promotion import check_and_promote_duplicate

    scope, scope_id = scope_params

    # Validate confidence threshold
    if request.confidence < PROVISIONAL_THRESHOLD:
        return SaveLearningResponse(
            uuid=None,
            status="rejected",
            is_duplicate=False,
            reinforced_uuid=None,
            message=f"Confidence {request.confidence}% is below provisional threshold ({PROVISIONAL_THRESHOLD}%)",
        )

    # Validate content for verbosity (validation-first approach per decision d3)
    formatter = get_episode_formatter()
    try:
        formatter.validate_content(request.content)
    except EpisodeValidationError as e:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "Content validation failed",
                "message": e.message,
                "detected_patterns": e.detected_patterns,
                "hint": "Write declarative facts, not conversational advice. Remove detected patterns and resubmit.",
            },
        ) from e

    # Check for duplicate/reinforcement
    try:
        reinforcement = await check_and_promote_duplicate(
            content=request.content,
            confidence=request.confidence,
        )

        if reinforcement.found_match:
            status = "canonical" if reinforcement.promoted else "provisional"
            return SaveLearningResponse(
                uuid=None,
                status=status,
                is_duplicate=True,
                reinforced_uuid=reinforcement.matched_uuid,
                message=f"Reinforced existing learning (new confidence: {reinforcement.new_confidence}%)",
            )
    except Exception as e:
        # Log but continue - duplicate check is optional
        import logging

        logging.getLogger(__name__).warning("Duplicate check failed: %s", e)

    # Determine status based on confidence
    status = (
        LearningStatus.CANONICAL
        if request.confidence >= CANONICAL_THRESHOLD
        else LearningStatus.PROVISIONAL
    )

    # Build source description
    tier = (
        InjectionTier.GUARDRAIL
        if request.category == MemoryCategory.TROUBLESHOOTING_GUIDE
        else InjectionTier.REFERENCE
    )
    source_description = formatter._build_source_description(
        category=request.category,
        tier=tier,
        origin=EpisodeOrigin.LEARNING,
        confidence=request.confidence,
        is_anti_pattern=(request.category == MemoryCategory.TROUBLESHOOTING_GUIDE),
    )
    source_description += f" status:{status.value}"
    if request.context:
        source_description += f" context:{request.context[:100]}"

    # Store the learning
    try:
        service = get_memory_service(scope=scope, scope_id=scope_id)
        uuid = await service.add_episode(
            content=request.content,
            source=MemorySource.SYSTEM,
            source_description=source_description,
        )

        return SaveLearningResponse(
            uuid=uuid,
            status=status.value,
            is_duplicate=False,
            reinforced_uuid=None,
            message=f"Saved as {status.value} learning",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save learning: {e}",
        ) from e


@router.post(
    "/golden-standards/seed", response_model=GoldenStandardResponse, tags=["golden-standards"]
)
async def api_seed_golden_standards() -> GoldenStandardResponse:
    """
    Seed the database with predefined golden standards.

    Creates golden standards for core Agent Hub patterns and constraints.
    Safe to call multiple times - will not create duplicates.
    """
    try:
        count = await seed_golden_standards()
        return GoldenStandardResponse(
            success=True,
            message=f"Seeded {count} golden standards",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to seed golden standards: {e}",
        ) from e


# Metrics Dashboard Endpoint


class VariantMetrics(BaseModel):
    """Aggregated metrics for a single variant."""

    variant: str = Field(..., description="Variant name")
    injection_count: int = Field(..., description="Total number of injections")
    success_count: int = Field(..., description="Number of successful tasks")
    fail_count: int = Field(..., description="Number of failed tasks")
    unknown_count: int = Field(..., description="Number with unknown outcome")
    success_rate: float = Field(..., description="Success rate (0-1)")
    citation_rate: float = Field(..., description="Memories cited / loaded ratio")
    avg_latency_ms: float = Field(..., description="Average injection latency")
    avg_tokens: float = Field(..., description="Average tokens injected")


class TimePeriodMetrics(BaseModel):
    """Metrics aggregated by time period."""

    period: str = Field(..., description="Time period (e.g., '2026-01-21', 'week-3')")
    injection_count: int
    avg_success_rate: float
    avg_citation_rate: float


class MetricsDashboardResponse(BaseModel):
    """Response from metrics dashboard endpoint."""

    total_injections: int = Field(..., description="Total injection count in period")
    period_start: str = Field(..., description="Start of analysis period")
    period_end: str = Field(..., description="End of analysis period")
    by_variant: list[VariantMetrics] = Field(..., description="Metrics broken down by variant")
    by_period: list[TimePeriodMetrics] = Field(..., description="Metrics by time period")
    overall_success_rate: float = Field(..., description="Overall success rate")
    overall_citation_rate: float = Field(..., description="Overall citation rate")


@router.get("/metrics", response_model=MetricsDashboardResponse, tags=["metrics"])
async def get_memory_metrics(
    days: Annotated[int, Query(ge=1, le=90, description="Days to look back")] = 7,
    period: Annotated[
        str,
        Query(description="Aggregation period: hour, day (default), week"),
    ] = "day",
    variant_filter: Annotated[
        str | None,
        Query(description="Filter by variant (BASELINE, ENHANCED, MINIMAL, AGGRESSIVE)"),
    ] = None,
    project_id_filter: Annotated[
        str | None,
        Query(description="Filter by project_id"),
    ] = None,
) -> MetricsDashboardResponse:
    """
    Get memory injection metrics for dashboard.

    Returns aggregated metrics including:
    - Injection counts by variant
    - Success and citation rates
    - Latency and token usage
    - Time-series breakdown by hour/day/week

    Useful for monitoring A/B test performance and tuning parameters.
    """
    from collections import defaultdict
    from datetime import UTC, timedelta

    from sqlalchemy import select

    from app.db import _get_session_factory
    from app.models import MemoryInjectionMetric

    session_factory = _get_session_factory()
    end_date = datetime.now(UTC)
    start_date = end_date - timedelta(days=days)

    try:
        async with session_factory() as session:
            query = select(MemoryInjectionMetric).where(
                MemoryInjectionMetric.created_at >= start_date,
                MemoryInjectionMetric.created_at <= end_date,
            )

            if variant_filter:
                query = query.where(MemoryInjectionMetric.variant == variant_filter)
            if project_id_filter:
                query = query.where(MemoryInjectionMetric.project_id == project_id_filter)

            result = await session.execute(query)
            records = result.scalars().all()

        # Aggregate by variant
        variant_data: dict[str, dict] = defaultdict(
            lambda: {
                "count": 0,
                "success": 0,
                "fail": 0,
                "unknown": 0,
                "latency_sum": 0,
                "tokens_sum": 0,
                "loaded_sum": 0,
                "cited_sum": 0,
            }
        )

        # Aggregate by time period
        period_data: dict[str, dict] = defaultdict(
            lambda: {"count": 0, "success": 0, "known": 0, "loaded": 0, "cited": 0}
        )

        for record in records:
            v = record.variant or "BASELINE"
            vd = variant_data[v]

            vd["count"] += 1
            if record.task_succeeded is True:
                vd["success"] += 1
            elif record.task_succeeded is False:
                vd["fail"] += 1
            else:
                vd["unknown"] += 1

            vd["latency_sum"] += record.injection_latency_ms or 0
            vd["tokens_sum"] += record.total_tokens or 0

            loaded = record.memories_loaded or []
            cited = record.memories_cited or []
            vd["loaded_sum"] += len(loaded) if isinstance(loaded, list) else 0
            vd["cited_sum"] += len(cited) if isinstance(cited, list) else 0

            # Time period aggregation
            created = record.created_at
            if period == "hour":
                period_key = created.strftime("%Y-%m-%d %H:00")
            elif period == "week":
                week_num = created.isocalendar()[1]
                period_key = f"{created.year}-W{week_num:02d}"
            else:  # day
                period_key = created.strftime("%Y-%m-%d")

            pd = period_data[period_key]
            pd["count"] += 1
            if record.task_succeeded is True:
                pd["success"] += 1
                pd["known"] += 1
            elif record.task_succeeded is False:
                pd["known"] += 1
            pd["loaded"] += len(loaded) if isinstance(loaded, list) else 0
            pd["cited"] += len(cited) if isinstance(cited, list) else 0

        # Build variant metrics
        by_variant = []
        for variant, data in sorted(variant_data.items()):
            count = data["count"]
            known = data["success"] + data["fail"]
            success_rate = data["success"] / known if known > 0 else 0.0
            citation_rate = (
                data["cited_sum"] / data["loaded_sum"] if data["loaded_sum"] > 0 else 0.0
            )

            by_variant.append(
                VariantMetrics(
                    variant=variant,
                    injection_count=count,
                    success_count=data["success"],
                    fail_count=data["fail"],
                    unknown_count=data["unknown"],
                    success_rate=round(success_rate, 3),
                    citation_rate=round(citation_rate, 3),
                    avg_latency_ms=round(data["latency_sum"] / count, 1) if count > 0 else 0.0,
                    avg_tokens=round(data["tokens_sum"] / count, 1) if count > 0 else 0.0,
                )
            )

        # Build period metrics
        by_period = []
        for period_key in sorted(period_data.keys()):
            data = period_data[period_key]
            success_rate = data["success"] / data["known"] if data["known"] > 0 else 0.0
            citation_rate = data["cited"] / data["loaded"] if data["loaded"] > 0 else 0.0

            by_period.append(
                TimePeriodMetrics(
                    period=period_key,
                    injection_count=data["count"],
                    avg_success_rate=round(success_rate, 3),
                    avg_citation_rate=round(citation_rate, 3),
                )
            )

        # Overall metrics
        total_success = sum(d["success"] for d in variant_data.values())
        total_known = sum(d["success"] + d["fail"] for d in variant_data.values())
        total_loaded = sum(d["loaded_sum"] for d in variant_data.values())
        total_cited = sum(d["cited_sum"] for d in variant_data.values())

        overall_success = total_success / total_known if total_known > 0 else 0.0
        overall_citation = total_cited / total_loaded if total_loaded > 0 else 0.0

        return MetricsDashboardResponse(
            total_injections=len(records),
            period_start=start_date.isoformat(),
            period_end=end_date.isoformat(),
            by_variant=by_variant,
            by_period=by_period,
            overall_success_rate=round(overall_success, 3),
            overall_citation_rate=round(overall_citation, 3),
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get metrics: {e}",
        ) from e
