"""Handler functions for complex memory agent endpoints."""

from app.services.memory.context_injector import ProgressiveContext
from app.services.memory.service import MemoryScope

from .memory_agent_schemas import (
    ProgressiveContextBlock,
    ProgressiveContextResponse,
    SaveLearningRequest,
    SaveLearningResponse,
    ScoringBreakdown,
)
from .memory_schemas import BudgetUsageResponse


async def build_progressive_context_response(
    query: str,
    scope: MemoryScope,
    scope_id: str | None,
    debug: bool,
    include_global: bool,
    task_type: str | None,
    variant_override: str | None,
    external_id: str | None,
    project_id: str | None,
) -> ProgressiveContextResponse:
    """Build progressive context response with all necessary data."""
    from app.services.memory.context_injector import (
        build_progressive_context,
        format_context_with_reference_index,
        get_relevance_debug_info,
    )
    from app.services.memory.variants import assign_variant

    # Determine variant
    assigned_variant = assign_variant(
        external_id=external_id,
        project_id=project_id or scope_id,
        variant_override=variant_override,
    )

    # Build progressive context
    context: ProgressiveContext = await build_progressive_context(
        query=query,
        scope=scope,
        scope_id=scope_id,
        include_global=include_global,
        task_type=task_type,
    )

    context.debug_info["variant"] = assigned_variant.value

    # Build reference index if enabled
    reference_episodes = await _build_reference_episodes(scope, scope_id)

    # Format for injection
    formatted = format_context_with_reference_index(
        context,
        reference_episodes=reference_episodes,
        include_citations=True,
    )

    # Build scoring breakdown if debug=True
    scoring_breakdown = _build_scoring_breakdown(context) if debug else None

    # Build budget usage response
    budget_usage_response = _build_budget_usage(context)

    return ProgressiveContextResponse(
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


async def _build_reference_episodes(
    scope: MemoryScope,
    scope_id: str | None,
) -> list[tuple[str, str | None, str, bool]] | None:
    """Build reference TOON index if enabled."""
    from app.services.memory.context_injector import build_reference_toon_index
    from app.services.memory.settings import get_memory_settings

    settings = await get_memory_settings()
    if not settings.reference_index_enabled:
        return None

    # Always include global scope references
    reference_episodes = await build_reference_toon_index(MemoryScope.GLOBAL, None)

    # Add project-specific references if project scope requested
    if scope == MemoryScope.PROJECT and scope_id:
        project_refs = await build_reference_toon_index(scope, scope_id)
        if project_refs:
            # Dedupe by UUID (global first, then project)
            seen_uuids = {r[0] for r in reference_episodes}
            reference_episodes.extend(r for r in project_refs if r[0] not in seen_uuids)

    return reference_episodes


def _build_scoring_breakdown(context: ProgressiveContext) -> list[ScoringBreakdown]:
    """Build scoring breakdown for debug mode."""
    scoring_breakdown = []

    for m in context.mandates:
        scoring_breakdown.append(
            ScoringBreakdown(
                uuid=m.uuid[:8] if m.uuid else "unknown",
                score=m.relevance_score,
                semantic=m.relevance_score,
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

    return scoring_breakdown


def _build_budget_usage(context: ProgressiveContext) -> BudgetUsageResponse | None:
    """Build budget usage response from context."""
    if not context.budget_usage:
        return None

    return BudgetUsageResponse(
        mandates_tokens=context.budget_usage.mandates_tokens,
        guardrails_tokens=context.budget_usage.guardrails_tokens,
        reference_tokens=context.budget_usage.reference_tokens,
        total_tokens=context.budget_usage.total_tokens,
        total_budget=context.budget_usage.total_budget,
        remaining=context.budget_usage.remaining,
        hit_limit=context.budget_usage.hit_limit,
        mandates_injected=len(context.mandates),
        guardrails_injected=len(context.guardrails),
        reference_injected=len(context.reference),
        mandates_total=context.budget_usage.mandates_total,
        guardrails_total=context.budget_usage.guardrails_total,
        reference_total=context.budget_usage.reference_total,
    )


async def handle_save_learning(
    request: SaveLearningRequest,
    scope: MemoryScope,
    scope_id: str | None,
) -> SaveLearningResponse:
    """Handle save learning request with all validation and storage logic."""
    from graphiti_core.utils.datetime_utils import utc_now

    from app.services.memory.episode_creator import get_episode_creator
    from app.services.memory.episode_helpers import EpisodeOrigin, build_source_description
    from app.services.memory.episode_validation import EpisodeValidator
    from app.services.memory.ingestion_config import LEARNING
    from app.services.memory.learning_extractor import (
        CANONICAL_THRESHOLD,
        PROVISIONAL_THRESHOLD,
        LearningStatus,
    )
    from app.services.memory.service import MemoryCategory, MemorySource

    # Validate confidence threshold
    if request.confidence < PROVISIONAL_THRESHOLD:
        return SaveLearningResponse(
            uuid=None,
            status="rejected",
            is_duplicate=False,
            reinforced_uuid=None,
            message=f"Confidence {request.confidence}% is below provisional threshold ({PROVISIONAL_THRESHOLD}%)",
        )

    # Validate content
    EpisodeValidator.validate_content(request.content)

    # Check for duplicate/reinforcement
    reinforcement = await _check_duplicate(request.content, request.confidence)
    if reinforcement:
        return reinforcement

    # Determine status and create learning
    status = (
        LearningStatus.CANONICAL
        if request.confidence >= CANONICAL_THRESHOLD
        else LearningStatus.PROVISIONAL
    )

    # Build source description
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

    if not result.success:
        raise ValueError(f"Failed to save learning: {result.validation_error}")

    new_uuid = result.uuid or ""

    # Set additional properties
    await _set_episode_properties(new_uuid, request.pinned, request.trigger_task_types)

    return SaveLearningResponse(
        uuid=new_uuid,
        status=status.value,
        is_duplicate=False,
        reinforced_uuid=None,
        message=f"Saved as {status.value} learning",
    )


async def _check_duplicate(content: str, confidence: int) -> SaveLearningResponse | None:
    """Check for duplicate learning and return response if found."""
    from app.services.memory.promotion import check_and_promote_duplicate

    try:
        reinforcement = await check_and_promote_duplicate(
            content=content,
            confidence=confidence,
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
        import logging

        logging.getLogger(__name__).warning("Duplicate check failed: %s", e)

    return None


async def _set_episode_properties(
    uuid: str,
    pinned: bool,
    trigger_task_types: list[str] | None,
) -> None:
    """Set additional properties on episode if provided."""
    if not uuid or (not pinned and not trigger_task_types):
        return

    from app.services.memory.graphiti_client import (
        set_episode_pinned,
        set_episode_trigger_task_types,
    )

    if pinned:
        await set_episode_pinned(uuid, True)
    if trigger_task_types:
        await set_episode_trigger_task_types(uuid, trigger_task_types)
