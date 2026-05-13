"""
Learning extraction service for session transcripts.

Extracts learnings from Claude Code sessions and stores them in memory
with confidence scoring and provisional/canonical status.
"""

import logging
from datetime import UTC, datetime

from .episode_creator import get_episode_creator
from .episode_helpers import EpisodeOrigin, build_source_description
from .ingestion_config import LEARNING
from .learning_constants import CANONICAL_THRESHOLD, EXTRACTION_PROMPT, PROVISIONAL_THRESHOLD
from .learning_models import (
    ExtractedLearning,
    ExtractionResult,
    ExtractLearningsRequest,
    LearningStatus,
    LearningType,
)
from .learning_utils import parse_learnings_json
from .memory_models import InjectionTier
from .service import MemoryCategory, MemoryScope, MemorySource

# Re-export models and constants for backward compatibility
__all__ = [
    "CANONICAL_THRESHOLD", "EXTRACTION_PROMPT", "PROVISIONAL_THRESHOLD",
    "ExtractLearningsRequest", "ExtractedLearning", "ExtractionResult",
    "LearningStatus", "LearningType", "_parse_learnings_json", "extract_learnings",
]

# Map internal name for tests
_parse_learnings_json = parse_learnings_json

logger = logging.getLogger(__name__)


async def _run_llm_extraction(prompt: str) -> list[ExtractedLearning]:
    """Call the learning-extractor agent and parse the response."""
    from app.api.complete.core import complete_internal
    from app.db import _get_session_factory
    from app.services.agent_model_router import RoutingContext
    from app.services.agent_routing_utils import resolve_agent

    session_factory = _get_session_factory()
    async with session_factory() as db:
        try:
            resolved = await resolve_agent(
                "learning-extractor",
                db,
                RoutingContext(),
            )
        except Exception:
            logger.error("learning-extractor agent not found")
            return []
        agent = resolved.agent
        response = await complete_internal(
            messages=[{"role": "user", "content": prompt}],
            model=resolved.model,
            provider=resolved.provider,
            temperature=agent.temperature,
            project_id="agent-hub",
            db=db,
            agent_slug=agent.slug,
            use_memory=False,
            enable_caching=False,
            skip_cache=True,
        )
    return parse_learnings_json(response.content)


async def extract_learnings(request: ExtractLearningsRequest) -> ExtractionResult:
    """Extract learnings from a session transcript using LLM analysis."""
    start_time = datetime.now(UTC)
    result = ExtractionResult(session_id=request.session_id)

    transcript = request.transcript
    if len(transcript) > 15000:
        transcript = "...[truncated]...\n" + transcript[-12000:]
        logger.info("Truncated transcript from %d to %d chars", len(request.transcript), len(transcript))

    from app.services.prompt_service import get_prompt_content

    template = await get_prompt_content("learning-extraction", EXTRACTION_PROMPT)
    prompt = template.format(transcript=transcript)

    try:
        result.learnings = await _run_llm_extraction(prompt)
    except Exception as e:
        logger.error("Learning extraction failed for session %s: %s", request.session_id, e)
        result.processing_time_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
        return result

    await _store_learnings(result, result.learnings)
    result.processing_time_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
    logger.info(
        "Extraction complete: session=%s stored=%d (canonical=%d, provisional=%d) skipped=%d time=%dms",
        request.session_id, result.stored_count, result.canonical_count,
        result.provisional_count, result.skipped_count, result.processing_time_ms,
    )
    return result


async def _store_learnings(result: ExtractionResult, learnings: list[ExtractedLearning]) -> None:
    """Store extracted learnings in memory."""
    from .promotion import check_and_promote_duplicate

    creator = get_episode_creator(scope=MemoryScope.GLOBAL)

    for learning in learnings:
        if learning.confidence < PROVISIONAL_THRESHOLD:
            result.skipped_count += 1
            continue

        reinforcement = await check_and_promote_duplicate(content=learning.content, confidence=learning.confidence)
        if reinforcement.found_match:
            result.stored_count += 1
            result.canonical_count += 1 if reinforcement.promoted else 0
            result.provisional_count += 0 if reinforcement.promoted else 1
            continue

        status = LearningStatus.CANONICAL if learning.confidence >= CANONICAL_THRESHOLD else LearningStatus.PROVISIONAL
        is_guardrail = learning.category == "troubleshooting_guide"
        tier = InjectionTier.GUARDRAIL if is_guardrail else InjectionTier.REFERENCE
        mem_category = MemoryCategory.GUARDRAIL if is_guardrail else MemoryCategory.REFERENCE

        source_description = build_source_description(
            category=mem_category, tier=tier, origin=EpisodeOrigin.LEARNING,
            confidence=int(learning.confidence), is_anti_pattern=is_guardrail,
        ) + f" status:{status.value}"

        create_result = await creator.create(
            content=learning.content,
            name=f"learning_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}_{result.stored_count}",
            config=LEARNING,
            source_description=source_description,
            reference_time=datetime.now(UTC),
            source=MemorySource.SYSTEM,
        )

        if create_result.success:
            result.stored_count += 1
            if status == LearningStatus.CANONICAL:
                result.canonical_count += 1
            else:
                result.provisional_count += 1
        else:
            logger.error("Failed to store learning: %s", create_result.validation_error)
            result.skipped_count += 1
