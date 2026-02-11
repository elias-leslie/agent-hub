"""Handler functions for complex memory agent endpoints."""

import logging
import time

from app.services.memory.context_injector import ProgressiveContext
from app.services.memory.service import MemoryScope

from .memory_agent_helpers import (
    build_budget_usage,
    build_reference_episodes,
    build_scoring_breakdown,
    check_duplicate,
    set_episode_properties,
)
from .memory_agent_schemas import (
    ProgressiveContextBlock,
    ProgressiveContextResponse,
    SaveLearningRequest,
    SaveLearningResponse,
)

logger = logging.getLogger(__name__)


async def build_progressive_context_response(
    query: str,
    scope: MemoryScope,
    scope_id: str | None,
    debug: bool,
    include_global: bool,
    task_type: str | None,
    phase: str | None = None,
    variant_override: str | None = None,
    external_id: str | None = None,
    project_id: str | None = None,
    session_id: str | None = None,
) -> ProgressiveContextResponse:
    """Build progressive context response with all necessary data."""
    from app.services.memory.context_injector import (
        build_progressive_context,
        format_context_with_reference_index,
        get_relevance_debug_info,
    )
    from app.services.memory.metrics_collector import InjectionMetrics, record_injection_metrics
    from app.services.memory.usage_tracker import track_loaded_batch
    from app.services.memory.variants import assign_variant

    start_time = time.monotonic()

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
        phase=phase,
    )

    context.debug_info["variant"] = assigned_variant.value

    # Build reference index if enabled
    reference_episodes = await build_reference_episodes(scope, scope_id)

    # Format for injection
    formatted = format_context_with_reference_index(
        context,
        reference_episodes=reference_episodes,
        include_citations=True,
    )

    # Track loaded memories in Neo4j (always, for usage counters)
    loaded_uuids = context.get_loaded_uuids()
    if loaded_uuids:
        await track_loaded_batch(loaded_uuids)

    # Record injection metrics in PostgreSQL (for task outcome correlation)
    latency_ms = int((time.monotonic() - start_time) * 1000)
    if session_id or external_id:
        record_injection_metrics(InjectionMetrics(
            injection_latency_ms=latency_ms,
            mandates_count=len(context.mandates),
            guardrails_count=len(context.guardrails),
            reference_count=len(context.reference),
            total_tokens=context.total_tokens,
            query=query,
            variant=assigned_variant.value,
            session_id=session_id,
            external_id=external_id,
            project_id=project_id or scope_id,
            memories_loaded=loaded_uuids,
        ))
        logger.info(
            "Progressive-context metrics: session=%s external=%s loaded=%d latency=%dms",
            session_id, external_id, len(loaded_uuids), latency_ms,
        )

    # Build scoring breakdown if debug=True
    scoring_breakdown = build_scoring_breakdown(context) if debug else None

    # Build budget usage response
    budget_usage_response = build_budget_usage(context)

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

    # Validate summary
    EpisodeValidator.validate_summary(request.summary)

    # Check for duplicate/reinforcement
    reinforcement = await check_duplicate(request.content, request.confidence)
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
    await set_episode_properties(new_uuid, request.pinned, request.trigger_task_types)

    return SaveLearningResponse(
        uuid=new_uuid,
        status=status.value,
        is_duplicate=False,
        reinforced_uuid=None,
        message=f"Saved as {status.value} learning",
    )
