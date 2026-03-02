"""Tag-based filtering for progressive context episodes."""

from __future__ import annotations

import logging

from .service import MemorySearchResult

logger = logging.getLogger(__name__)


def _has_excluded_tag(ep_tags: list[str], exclude_tags: list[str]) -> bool:
    """Return True if the episode contains any excluded tag."""
    return any(tag in ep_tags for tag in exclude_tags)


def _has_required_tag(ep_tags: list[str], include_tags: list[str]) -> bool:
    """Return True if the episode contains at least one required tag."""
    return any(tag in ep_tags for tag in include_tags)


def _episode_passes_filters(
    ep_tags: list[str],
    include_tags: list[str],
    exclude_tags: list[str],
) -> bool:
    """Return True if an episode should be kept after applying tag filters."""
    if exclude_tags and _has_excluded_tag(ep_tags, exclude_tags):
        return False
    return not (include_tags and not _has_required_tag(ep_tags, include_tags))


def filter_by_tags(
    episodes: list[MemorySearchResult],
    include_tags: list[str],
    exclude_tags: list[str],
) -> list[MemorySearchResult]:
    """Filter episodes by include/exclude tags using the episode's tags field.

    Tags are carried on MemorySearchResult from the memories table.
    """
    if not include_tags and not exclude_tags:
        return episodes

    filtered = [
        ep
        for ep in episodes
        if _episode_passes_filters(ep.tags or [], include_tags, exclude_tags)
    ]

    if len(filtered) < len(episodes):
        logger.info(
            "Tag filter: %d -> %d episodes (include=%s, exclude=%s)",
            len(episodes),
            len(filtered),
            include_tags,
            exclude_tags,
        )

    return filtered
