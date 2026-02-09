"""Episode storage for session summaries.

Stores generated session summaries as episodes in the knowledge graph
using the EpisodeCreator pattern.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def store_as_episode(
    session_id: str,
    project_id: str,
    summary_text: str,
) -> str | None:
    """Store session summary as a memory episode in the knowledge graph.

    Uses the EpisodeCreator single-funnel pattern with the LEARNING
    ingestion profile (reference tier, 5min dedup window).

    Args:
        session_id: Session UUID for naming.
        project_id: Project ID for source description.
        summary_text: The generated summary text.

    Returns:
        The episode UUID if stored successfully, None otherwise.
    """
    try:
        from graphiti_core.utils.datetime_utils import utc_now

        from app.services.memory.episode_creator import get_episode_creator
        from app.services.memory.ingestion_config import LEARNING
        from app.services.memory.memory_models import MemoryScope

        creator = get_episode_creator(scope=MemoryScope.GLOBAL)
        result = await creator.create(
            content=f"[Session Summary: {session_id}]\n{summary_text}",
            name=f"session_summary_{session_id}_{utc_now().isoformat()}",
            config=LEARNING,
            source_description=f"session_summary session:{session_id} project:{project_id}",
            reference_time=utc_now(),
        )
        return result.uuid if result.success else None
    except Exception as e:
        logger.error("Failed to store session summary as episode: %s", e)
        return None
