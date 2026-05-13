"""Internal helpers for memory_rater — not part of the public API."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def build_rating_prompt(memory_contents: dict[str, str], transcript: str) -> str:
    """Build the LLM prompt for rating memories against a transcript."""
    memory_list = "\n".join(
        f"[{uuid[:8]}] {content[:200]}"
        for uuid, content in memory_contents.items()
    )

    return f"""You are rating injected memory episodes for an AI coding assistant session.

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


async def call_llm_for_ratings(session_id: str, prompt: str) -> str:
    """Call the memory-rater agent via complete_internal and return raw text.

    Returns:
        Raw LLM response text, or empty string on failure.
    """
    from app.api.complete.core import complete_internal
    from app.db import _get_session_factory
    from app.services.agent_model_router import RoutingContext
    from app.services.agent_routing_utils import resolve_agent

    session_factory = _get_session_factory()
    async with session_factory() as db:
        try:
            resolved = await resolve_agent(
                "memory-rater",
                db,
                RoutingContext(),
            )
        except Exception:
            logger.warning("memory-rater agent not found, skipping rating")
            return ""

        agent = resolved.agent
        result = await complete_internal(
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

    return result.content.strip()


def _parse_ratings(
    text: str,
    memory_contents: dict[str, str],
) -> dict[str, str]:
    """Parse LLM rating response into UUID -> rating map."""
    valid_ratings = {"helpful", "harmful", "neutral"}
    prefix_to_uuid = {uuid[:8]: uuid for uuid in memory_contents}

    ratings: dict[str, str] = {}
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or not line.startswith("["):
            continue

        bracket_end = line.find("]")
        if bracket_end < 0:
            continue

        prefix = line[1:bracket_end].strip()
        rating = line[bracket_end + 1:].strip().lower()

        if rating in valid_ratings and prefix in prefix_to_uuid:
            ratings[prefix_to_uuid[prefix]] = rating

    return ratings
