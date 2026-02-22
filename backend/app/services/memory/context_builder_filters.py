"""Tag-based filtering for progressive context episodes."""

from __future__ import annotations

import logging

from .service import MemorySearchResult

logger = logging.getLogger(__name__)


def filter_by_tags(
    episodes: list[MemorySearchResult],
    include_tags: list[str],
    exclude_tags: list[str],
) -> list[MemorySearchResult]:
    """Filter episodes by include/exclude tags using the episode's tags field.

    Tags are populated from Neo4j episode nodes and carried on MemorySearchResult.
    """
    if not include_tags and not exclude_tags:
        return episodes

    filtered = []
    for ep in episodes:
        ep_tags = ep.tags or []

        if exclude_tags and any(tag in ep_tags for tag in exclude_tags):
            continue

        if include_tags and not any(tag in ep_tags for tag in include_tags):
            continue

        filtered.append(ep)

    if len(filtered) < len(episodes):
        logger.info(
            "Tag filter: %d -> %d episodes (include=%s, exclude=%s)",
            len(episodes),
            len(filtered),
            include_tags,
            exclude_tags,
        )

    return filtered
