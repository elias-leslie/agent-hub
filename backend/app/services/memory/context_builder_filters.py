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
    """Filter episodes by include/exclude tags using episode content matching.

    Since MemorySearchResult doesn't carry tags directly, we filter based on
    tag keywords appearing in the episode content/summary. This is a heuristic
    approach — precise tag-based filtering requires tag data on each episode.
    """
    if not include_tags and not exclude_tags:
        return episodes

    filtered = []
    for ep in episodes:
        text = (ep.content or "").lower()

        if exclude_tags and any(tag.lower() in text for tag in exclude_tags):
            continue

        if include_tags and not any(tag.lower() in text for tag in include_tags):
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
