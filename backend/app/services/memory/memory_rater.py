"""Memory helpfulness rating for session analysis.

After a session ends, rates which injected memories were actually helpful
vs harmful based on the session transcript. This feeds into utility_score
via the helpful_count / harmful_count counters on memory records.

Called from the Hatchet summary workflow after summary generation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .memory_rater_helpers import _parse_ratings, build_rating_prompt, call_llm_for_ratings
from .session_queries import get_memories_loaded

logger = logging.getLogger(__name__)

# Only rate sessions with enough loaded memories to be meaningful
MIN_MEMORIES_TO_RATE = 3

# Cap memories sent to LLM to control token cost
MAX_MEMORIES_TO_RATE = 30


@dataclass
class RatingResult:
    """Result of memory rating for a session."""

    session_id: str
    memories_rated: int
    helpful_count: int
    harmful_count: int
    neutral_count: int


async def rate_session_memories(session_id: str, transcript: str) -> RatingResult:
    """Rate loaded memories for helpfulness based on session transcript.

    Steps:
    1. Get loaded memory UUIDs from injection metrics
    2. Fetch memory content from PostgreSQL via MemoryRepository
    3. Ask LLM to rate each as helpful/neutral/harmful
    4. Credit via track_helpful_batch / track_harmful_batch

    Args:
        session_id: Session to rate memories for
        transcript: Condensed session transcript

    Returns:
        RatingResult with counts
    """
    empty = RatingResult(session_id=session_id, memories_rated=0,
                         helpful_count=0, harmful_count=0, neutral_count=0)
    loaded_uuids = await get_memories_loaded(session_id)
    if len(loaded_uuids) < MIN_MEMORIES_TO_RATE:
        logger.debug("Session %s: only %d loaded memories, skipping rating",
                     session_id, len(loaded_uuids))
        return empty
    memory_contents = await _fetch_memory_contents(loaded_uuids[:MAX_MEMORIES_TO_RATE])
    if not memory_contents:
        return empty
    ratings = await _rate_via_llm(session_id, transcript, memory_contents)
    helpful = [u for u, r in ratings.items() if r == "helpful"]
    harmful = [u for u, r in ratings.items() if r == "harmful"]
    if helpful:
        from .usage_tracker import track_helpful_batch
        await track_helpful_batch(helpful)
    if harmful:
        from .usage_tracker import track_harmful_batch
        await track_harmful_batch(harmful)
    neutral_count = len(ratings) - len(helpful) - len(harmful)
    logger.info("Session %s: rated %d memories (helpful=%d, harmful=%d, neutral=%d)",
                session_id, len(ratings), len(helpful), len(harmful), neutral_count)
    return RatingResult(session_id=session_id, memories_rated=len(ratings),
                        helpful_count=len(helpful), harmful_count=len(harmful),
                        neutral_count=neutral_count)


async def _fetch_memory_contents(uuids: list[str]) -> dict[str, str]:
    """Fetch memory content from PostgreSQL via MemoryRepository.

    Returns:
        Dict mapping UUID to content string
    """
    from .repository import get_memory_repository

    repo = get_memory_repository()
    batch = await repo.batch_get(uuids)
    return {uuid: data["content"] for uuid, data in batch.items() if data.get("content")}


async def _rate_via_llm(
    session_id: str,
    transcript: str,
    memory_contents: dict[str, str],
) -> dict[str, str]:
    """Rate memories via Agent Hub's completion pipeline.

    Routes through ``complete_internal`` using the ``memory-rater`` agent so
    that model/temperature come from agent config and tokens are tracked.

    Returns:
        Dict mapping UUID to rating ("helpful", "harmful", or "neutral")
    """
    try:
        prompt = build_rating_prompt(memory_contents, transcript)
        text = await call_llm_for_ratings(session_id, prompt)
        if not text:
            logger.warning("LLM returned empty rating response for session %s", session_id)
            return {}
        return _parse_ratings(text, memory_contents)
    except Exception as e:
        logger.warning("Memory rating LLM call failed for session %s: %s", session_id, e)
        return {}
