"""Episode storage for session summaries.

Stores generated session summaries as episodes in the memory system
using the EpisodeCreator pattern.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


async def store_as_episode(
    session_id: str,
    project_id: str,
    summary_text: str,
) -> str | None:
    """Store session summary as a memory episode.

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
        from app.services.memory.episode_creator import get_episode_creator
        from app.services.memory.ingestion_config import LEARNING
        from app.services.memory.memory_models import MemoryScope
        from app.services.memory.repository import get_memory_repository

        now = datetime.now(UTC)
        creator = get_episode_creator(scope=MemoryScope.GLOBAL)
        result = await creator.create(
            content=f"[Session Summary: {session_id}]\n{summary_text}",
            name=f"session_summary_{session_id}_{now.isoformat()}",
            config=LEARNING,
            source_description=f"session_summary session:{session_id} project:{project_id}",
            reference_time=now,
        )

        # Tag as session summary via metadata so it's excluded from reference index injection
        if result.success and result.uuid:
            try:
                repo = get_memory_repository()
                await repo.update(
                    result.uuid,
                    metadata={"is_session_summary": True},
                )
            except Exception as e:
                logger.warning("Failed to tag session summary episode %s: %s", result.uuid, e)

        return result.uuid if result.success else None
    except Exception as e:
        logger.error("Failed to store session summary as episode: %s", e)
        return None
