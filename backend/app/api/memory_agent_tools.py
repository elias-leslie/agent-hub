"""Memory agent tools endpoints - for recording learnings during task execution."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.memory.episode_creator import get_episode_creator
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
from app.services.memory.service import MemoryCategory, MemoryScope, MemorySource
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
from app.services.memory.types import InjectionTier

from .memory_schemas import BudgetUsageResponse

router = APIRouter()


# Helper function for scope params
def get_scope_params(
    x_memory_scope: Annotated[str | None, Query()] = None,
    x_scope_id: Annotated[str | None, Query()] = None,
) -> tuple[MemoryScope, str | None]:
    """Get scope parameters from query params."""
    scope = MemoryScope.GLOBAL
    if x_memory_scope:
        scope_value = x_memory_scope.lower()
        valid_scopes = [s.value for s in MemoryScope]
        if scope_value in valid_scopes:
            scope = MemoryScope(scope_value)
    return scope, x_scope_id


@router.post("/record-discovery", response_model=RecordResponse)
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


@router.post("/record-gotcha", response_model=RecordResponse)
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


@router.post("/record-pattern", response_model=RecordResponse)
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


@router.get("/session-context", response_model=SessionContextResponse)
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


@router.post("/extract-learnings", response_model=ExtractionResult)
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


@router.post("/promote", response_model=PromotionResult)
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
    debug: dict[str, Any] | None = Field(None, description="Debug info when debug=True")
    scoring_breakdown: list[ScoringBreakdown] | None = Field(
        None, description="Scoring breakdown when debug=True"
    )
    budget_usage: BudgetUsageResponse | None = Field(
        None, description="Token budget usage tracking"
    )


@router.get("/progressive-context", response_model=ProgressiveContextResponse)
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
    task_type: Annotated[
        str | None,
        Query(
            description="Task type to trigger type-specific references (e.g., 'database', 'frontend')"
        ),
    ] = None,
) -> ProgressiveContextResponse:
    """
    Get 3-block progressive disclosure context for a query.

    Returns context in three blocks:
    - **Mandates**: Golden standards (confidence=100) - always injected
    - **Guardrails**: Anti-patterns and gotchas (TROUBLESHOOTING_GUIDE)
    - **Reference**: Patterns and workflows, including type-triggered references

    This endpoint is designed for SessionStart hooks to efficiently
    retrieve relevant context with minimal token usage (~150-200 tokens).

    **Task Type Triggering:**
    - Pass `task_type` (e.g., "database", "frontend") to inject type-specific references
    - References with matching trigger_task_types are automatically included

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
        build_reference_toon_index,
        format_context_with_reference_index,
        get_relevance_debug_info,
    )
    from app.services.memory.settings import get_memory_settings
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
        task_type=task_type,
    )

    # Store variant in debug info for downstream use
    context.debug_info["variant"] = assigned_variant.value

    # Build TOON reference index if enabled
    # Include global references when project scope is requested (matches mandate/guardrail behavior)
    settings = await get_memory_settings()
    reference_episodes: list[tuple[str, str | None, str, bool]] | None = None
    if settings.reference_index_enabled:
        # Always include global scope references
        reference_episodes = await build_reference_toon_index(MemoryScope.GLOBAL, None)
        # Add project-specific references if project scope requested
        if scope == MemoryScope.PROJECT and scope_id:
            project_refs = await build_reference_toon_index(scope, scope_id)
            if project_refs:
                # Dedupe by UUID (global first, then project)
                seen_uuids = {r[0] for r in reference_episodes}
                reference_episodes.extend(r for r in project_refs if r[0] not in seen_uuids)

    # Format for injection with TOON index
    formatted = format_context_with_reference_index(
        context,
        reference_episodes=reference_episodes,
        include_citations=True,
    )

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
    budget_usage_response = None
    if context.budget_usage:
        budget_usage_response = BudgetUsageResponse(
            mandates_tokens=context.budget_usage.mandates_tokens,
            guardrails_tokens=context.budget_usage.guardrails_tokens,
            reference_tokens=context.budget_usage.reference_tokens,
            total_tokens=context.budget_usage.total_tokens,
            total_budget=context.budget_usage.total_budget,
            remaining=context.budget_usage.remaining,
            hit_limit=context.budget_usage.hit_limit,
            # Populate injection counts from actual context
            mandates_injected=len(context.mandates),
            guardrails_injected=len(context.guardrails),
            reference_injected=len(context.reference),
            # Total counts from budget_usage if available
            mandates_total=context.budget_usage.mandates_total,
            guardrails_total=context.budget_usage.guardrails_total,
            reference_total=context.budget_usage.reference_total,
        )

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
        budget_usage=budget_usage_response,
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


@router.post("/canonical-context", response_model=CanonicalContextResponse)
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


class SaveLearningRequest(BaseModel):
    """Request to save a learning from a session."""

    content: str = Field(..., description="The learning content")
    summary: str = Field(
        ..., description="REQUIRED: Short action phrase (~20 chars) for TOON index"
    )
    injection_tier: InjectionTier = Field(
        InjectionTier.REFERENCE,
        description="Injection tier (mandate, guardrail, reference)",
    )
    confidence: int = Field(
        80,
        ge=0,
        le=100,
        description="Confidence level (0-100). 70+ is provisional, 90+ is canonical.",
    )
    context: str | None = Field(None, description="Optional context about the learning source")
    pinned: bool = Field(False, description="Pin episode (always inject regardless of budget)")
    trigger_task_types: list[str] | None = Field(
        None, description="Task types that trigger this reference (e.g., ['database', 'memory'])"
    )


class SaveLearningResponse(BaseModel):
    """Response from save_learning endpoint."""

    uuid: str | None = Field(None, description="UUID of the created learning")
    status: str = Field(..., description="provisional or canonical based on confidence")
    is_duplicate: bool = Field(False, description="True if similar learning exists")
    reinforced_uuid: str | None = Field(
        None, description="UUID of reinforced learning if duplicate"
    )
    message: str


@router.post("/save-learning", response_model=SaveLearningResponse)
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
      -d '{"content": "Always use async methods for DB operations", "injection_tier": "reference"}'
    ```
    """
    from app.services.memory.episode_helpers import EpisodeOrigin, build_source_description
    from app.services.memory.episode_validation import EpisodeValidationError, EpisodeValidator
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
    try:
        EpisodeValidator.validate_content(request.content)
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

    # Build source description - tier is directly from request
    source_description = build_source_description(
        category=MemoryCategory(request.injection_tier.value),
        tier=request.injection_tier,
        origin=EpisodeOrigin.LEARNING,
        confidence=request.confidence,
        is_anti_pattern=(request.injection_tier.value == "guardrail"),
    )
    source_description += f" status:{status.value}"
    if request.context:
        source_description += f" context:{request.context[:100]}"

    # Store the learning
    from graphiti_core.utils.datetime_utils import utc_now

    from app.services.memory.ingestion_config import LEARNING

    creator = get_episode_creator(scope=scope, scope_id=scope_id)
    result = await creator.create(
        content=request.content,
        name=f"learning_{utc_now().strftime('%Y%m%d_%H%M%S')}",
        config=LEARNING,
        source_description=source_description,
        source=MemorySource.SYSTEM,
        injection_tier=request.injection_tier.value,
        summary=request.summary,
    )

    if result.success:
        new_uuid = result.uuid or ""

        # Set additional properties if provided
        if new_uuid and (request.pinned or request.trigger_task_types):
            from app.services.memory.graphiti_client import (
                set_episode_pinned,
                set_episode_trigger_task_types,
            )

            if request.pinned:
                await set_episode_pinned(new_uuid, True)
            if request.trigger_task_types:
                await set_episode_trigger_task_types(new_uuid, request.trigger_task_types)

        return SaveLearningResponse(
            uuid=new_uuid,
            status=status.value,
            is_duplicate=False,
            reinforced_uuid=None,
            message=f"Saved as {status.value} learning",
        )
    else:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save learning: {result.validation_error}",
        )
