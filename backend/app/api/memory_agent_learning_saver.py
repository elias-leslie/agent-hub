"""Learning save logic for memory agent."""

from app.services.memory.service import MemoryScope

from .memory_agent_helpers import check_duplicate, set_episode_properties
from .memory_agent_schemas import SaveLearningRequest, SaveLearningResponse


async def validate_learning_request(request: SaveLearningRequest) -> SaveLearningResponse | None:
    """Validate learning request, return rejection response if invalid."""
    from app.services.memory.episode_validation import EpisodeValidator
    from app.services.memory.learning_extractor import PROVISIONAL_THRESHOLD

    if request.confidence < PROVISIONAL_THRESHOLD:
        return SaveLearningResponse(
            uuid=None,
            status="rejected",
            is_duplicate=False,
            reinforced_uuid=None,
            message=f"Confidence {request.confidence}% is below provisional threshold ({PROVISIONAL_THRESHOLD}%)",
        )

    EpisodeValidator.validate_content(
        request.content,
        tier=request.injection_tier.value,
        bypass_compactness=request.bypass_compactness,
    )
    EpisodeValidator.validate_summary(request.summary)
    EpisodeValidator.validate_reusability(request.content)
    return None


async def store_learning_episode(
    request: SaveLearningRequest,
    scope: MemoryScope,
    scope_id: str | None,
) -> tuple[str, str]:
    """Store learning episode and return UUID and status."""
    from datetime import UTC, datetime

    from app.services.memory.episode_creator import get_episode_creator
    from app.services.memory.episode_helpers import EpisodeOrigin, build_source_description
    from app.services.memory.ingestion_config import LEARNING
    from app.services.memory.learning_extractor import (
        CANONICAL_THRESHOLD,
        LearningStatus,
    )
    from app.services.memory.service import MemoryCategory, MemorySource

    status = (
        LearningStatus.CANONICAL
        if request.confidence >= CANONICAL_THRESHOLD
        else LearningStatus.PROVISIONAL
    )

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

    creator = get_episode_creator(scope=scope, scope_id=scope_id)
    result = await creator.create(
        content=request.content,
        name=f"learning_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}",
        config=LEARNING,
        source_description=source_description,
        source=MemorySource.SYSTEM,
        injection_tier=request.injection_tier.value,
        summary=request.summary,
        changed_by="save_learning",
        change_reason=request.change_reason or "Learning saved",
        bypass_compactness=request.bypass_compactness,
    )

    if not result.success:
        raise ValueError(f"Failed to save learning: {result.validation_error}")

    new_uuid = result.uuid or ""
    await set_episode_properties(
        new_uuid,
        request.pinned,
        request.trigger_task_types,
        request.trigger_phases,
        request.context_kind.value if request.context_kind is not None else None,
        request.applicability.model_dump() if request.applicability is not None else None,
        change_reason=request.change_reason or "Learning properties updated",
        render_mode=request.render_mode,
    )

    return new_uuid, status.value


async def save_learning_with_validation(
    request: SaveLearningRequest,
    scope: MemoryScope,
    scope_id: str | None,
) -> SaveLearningResponse:
    """Save learning with full validation and duplicate checking."""
    rejection = await validate_learning_request(request)
    if rejection:
        return rejection

    reinforcement = await check_duplicate(request.content, request.confidence)
    if reinforcement:
        return reinforcement

    new_uuid, status = await store_learning_episode(request, scope, scope_id)

    return SaveLearningResponse(
        uuid=new_uuid,
        status=status,
        is_duplicate=False,
        reinforced_uuid=None,
        message=f"Saved as {status} learning",
    )
