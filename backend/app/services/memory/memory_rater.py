"""Memory helpfulness rating for session analysis.

After a session ends, rates which injected memories were actually helpful
vs harmful based on the session transcript. This feeds into utility_score
via the helpful_count / harmful_count counters on Neo4j Episodic nodes.

Called from the Hatchet summary workflow after summary generation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

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


async def rate_session_memories(
    session_id: str,
    transcript: str,
) -> RatingResult:
    """Rate loaded memories for helpfulness based on session transcript.

    Steps:
    1. Get loaded memory UUIDs from injection metrics
    2. Fetch memory content from Neo4j
    3. Ask LLM to rate each as helpful/neutral/harmful
    4. Credit via track_helpful_batch / track_harmful_batch

    Args:
        session_id: Session to rate memories for
        transcript: Condensed session transcript

    Returns:
        RatingResult with counts
    """
    # 1. Get loaded UUIDs
    loaded_uuids = await get_memories_loaded(session_id)
    if len(loaded_uuids) < MIN_MEMORIES_TO_RATE:
        logger.debug(
            "Session %s: only %d loaded memories, skipping rating",
            session_id,
            len(loaded_uuids),
        )
        return RatingResult(
            session_id=session_id,
            memories_rated=0,
            helpful_count=0,
            harmful_count=0,
            neutral_count=0,
        )

    # 2. Fetch memory content from Neo4j
    memory_contents = await _fetch_memory_contents(loaded_uuids[:MAX_MEMORIES_TO_RATE])
    if not memory_contents:
        return RatingResult(
            session_id=session_id,
            memories_rated=0,
            helpful_count=0,
            harmful_count=0,
            neutral_count=0,
        )

    # 3. Ask LLM to rate
    ratings = await _rate_via_llm(session_id, transcript, memory_contents)

    # 4. Credit helpful/harmful
    helpful_uuids = [uuid for uuid, rating in ratings.items() if rating == "helpful"]
    harmful_uuids = [uuid for uuid, rating in ratings.items() if rating == "harmful"]

    if helpful_uuids:
        from .usage_tracker import track_helpful_batch

        await track_helpful_batch(helpful_uuids)

    if harmful_uuids:
        from .usage_tracker import track_harmful_batch

        await track_harmful_batch(harmful_uuids)

    neutral_count = len(ratings) - len(helpful_uuids) - len(harmful_uuids)

    logger.info(
        "Session %s: rated %d memories (helpful=%d, harmful=%d, neutral=%d)",
        session_id,
        len(ratings),
        len(helpful_uuids),
        len(harmful_uuids),
        neutral_count,
    )

    return RatingResult(
        session_id=session_id,
        memories_rated=len(ratings),
        helpful_count=len(helpful_uuids),
        harmful_count=len(harmful_uuids),
        neutral_count=neutral_count,
    )


async def _fetch_memory_contents(uuids: list[str]) -> dict[str, str]:
    """Fetch memory content from Neo4j for rating.

    Returns:
        Dict mapping UUID to content string
    """
    from .episode_operations import batch_get_episodes
    from .graphiti_client import get_graphiti

    graphiti = get_graphiti()
    driver = graphiti.driver

    episodes = await batch_get_episodes(driver, uuids)
    return {
        uuid: ep["content"]
        for uuid, ep in episodes.items()
        if ep.get("content")
    }


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
    # Build memory list for prompt
    memory_list = "\n".join(
        f"[{uuid[:8]}] {content[:200]}"
        for uuid, content in memory_contents.items()
    )

    prompt = f"""You are rating injected memory episodes for an AI coding assistant session.

For each memory below, determine if it was HELPFUL, HARMFUL, or NEUTRAL based on the session transcript.

- HELPFUL: The memory was relevant and the agent followed or benefited from it
- HARMFUL: The memory was misleading, outdated, or caused the agent to make mistakes
- NEUTRAL: The memory was loaded but neither helped nor hurt

MEMORIES:
{memory_list}

TRANSCRIPT (condensed):
{transcript[:6000]}

Rate each memory. Respond with ONLY lines in this format (one per memory):
[uuid8] helpful|harmful|neutral

Example:
[abc12345] helpful
[def67890] neutral"""

    try:
        from app.api.complete.core import complete_internal
        from app.db import _get_session_factory
        from app.services.agent_routing import get_provider_for_model
        from app.services.agent_service import get_agent_service

        agent_service = get_agent_service()
        session_factory = _get_session_factory()
        async with session_factory() as db:
            agent = await agent_service.get_by_slug(db, "memory-rater")
            if not agent:
                logger.warning("memory-rater agent not found, skipping rating")
                return {}

            provider = get_provider_for_model(agent.primary_model_id)
            result = await complete_internal(
                messages=[{"role": "user", "content": prompt}],
                model=agent.primary_model_id,
                provider=provider,
                temperature=agent.temperature,
                project_id="agent-hub",
                db=db,
                agent_slug=agent.slug,
                use_memory=False,
                enable_caching=False,
                skip_cache=True,
            )

        text = result.content.strip()
        if not text:
            logger.warning("LLM returned empty rating response for session %s", session_id)
            return {}

        return _parse_ratings(text, memory_contents)

    except Exception as e:
        logger.warning("Memory rating LLM call failed for session %s: %s", session_id, e)
        return {}


def _parse_ratings(
    text: str,
    memory_contents: dict[str, str],
) -> dict[str, str]:
    """Parse LLM rating response into UUID -> rating map."""
    valid_ratings = {"helpful", "harmful", "neutral"}
    # Build prefix -> full UUID map
    prefix_to_uuid = {uuid[:8]: uuid for uuid in memory_contents}

    ratings: dict[str, str] = {}
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or not line.startswith("["):
            continue

        # Parse [uuid8] rating
        bracket_end = line.find("]")
        if bracket_end < 0:
            continue

        prefix = line[1:bracket_end].strip()
        rating = line[bracket_end + 1 :].strip().lower()

        if rating in valid_ratings and prefix in prefix_to_uuid:
            ratings[prefix_to_uuid[prefix]] = rating

    return ratings
