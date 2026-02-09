"""
Session history retrieval operations.

Retrieves recent session episodes with relevant insights and recommendations.
"""

import logging
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from graphiti_core import Graphiti
    from graphiti_core.nodes import EpisodeType
else:
    Graphiti = None
    EpisodeType = None

from .memory_models import MemoryCategory, MemoryEpisode, MemoryScope
from .memory_utils import map_episode_type
from .search_helpers import map_tier_to_category

logger = logging.getLogger(__name__)


class RawEpisode(Protocol):
    """Protocol for raw episode from Graphiti."""

    uuid: str
    name: str
    content: str
    source: "EpisodeType"
    source_description: str
    created_at: Any
    valid_at: Any
    entity_edges: list[str]


def _is_relevant_category(tier: str | None) -> bool:
    """Check if episode tier maps to a session-relevant category."""
    category = map_tier_to_category(tier)
    return category in {MemoryCategory.REFERENCE, MemoryCategory.GUARDRAIL}


def _convert_to_memory_episode(
    ep: RawEpisode, scope: MemoryScope, scope_id: str | None
) -> MemoryEpisode:
    """Convert raw episode to MemoryEpisode."""
    tier = getattr(ep, "injection_tier", None)
    category = map_tier_to_category(tier)

    return MemoryEpisode(
        uuid=ep.uuid,
        name=ep.name,
        content=ep.content,
        source=map_episode_type(ep.source),
        category=category,
        scope=scope,
        scope_id=scope_id,
        source_description=ep.source_description,
        created_at=ep.created_at,
        valid_at=ep.valid_at,
        entities=ep.entity_edges,
    )


async def get_session_history(
    graphiti: "Graphiti",
    group_id: str,
    scope: MemoryScope,
    scope_id: str | None,
    num_sessions: int = 5,
) -> list[MemoryEpisode]:
    """Get recent session recommendations and insights."""
    from graphiti_core.utils.datetime_utils import utc_now

    episodes_raw: Any = await graphiti.retrieve_episodes(
        reference_time=utc_now(),
        last_n=num_sessions * 10,
        group_ids=[group_id],
    )

    episodes: list[MemoryEpisode] = []
    for ep in episodes_raw:
        tier = getattr(ep, "injection_tier", None)
        if _is_relevant_category(tier):
            episodes.append(_convert_to_memory_episode(ep, scope, scope_id))
            if len(episodes) >= num_sessions:
                break

    return episodes
