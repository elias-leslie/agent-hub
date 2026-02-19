"""Episode chunking utilities for splitting large content."""

import re
from typing import TYPE_CHECKING

from .memory_models import FormattedEpisode, InjectionTier
from .service import MemoryCategory

if TYPE_CHECKING:
    from .episode_formatter import EpisodeFormatter


def _extract_section_title(section: str) -> str | None:
    """Extract the title from an H2 header in a markdown section."""
    title_match = re.match(r"^## (.+?)$", section, re.MULTILINE)
    return title_match.group(1).strip() if title_match else None


def _is_anti_pattern_section(section: str) -> bool:
    """Return True if the section content indicates an anti-pattern."""
    return bool(
        re.search(r"anti.?pattern|don\'?t|avoid|never|wrong|bad", section, re.IGNORECASE)
    )


def _format_section_episode(
    section: str,
    source_file: str,
    category: "MemoryCategory",
    formatter: "EpisodeFormatter",
) -> "FormattedEpisode":
    """Format a single markdown section as a FormattedEpisode."""
    title = _extract_section_title(section)
    is_anti = _is_anti_pattern_section(section)
    return formatter.format_learning(
        content=section,
        category=category,
        source_file=source_file,
        title=title,
        tier=InjectionTier.GUARDRAIL if is_anti else InjectionTier.REFERENCE,
        is_golden=True,  # Migrated rules are golden
        is_anti_pattern=is_anti,
        confidence=100,
        validate=False,  # Markdown sections use ## headers, not **Topic**: format
    )


def chunk_markdown_by_sections(
    content: str,
    source_file: str,
    category: MemoryCategory,
    formatter: "EpisodeFormatter",
    *,
    min_chunk_size: int = 50,
) -> list[FormattedEpisode]:
    """
    Split markdown content by H2 headers into separate episodes.

    Per Gemini recommendation: don't store whole files as single episodes.

    Args:
        content: Full markdown content
        source_file: Original source file
        category: Memory category for all chunks
        formatter: EpisodeFormatter instance to use
        min_chunk_size: Skip chunks smaller than this

    Returns:
        List of FormattedEpisodes, one per section
    """
    episodes = []

    # Split by H2 headers
    sections = re.split(r"(?=^## )", content, flags=re.MULTILINE)

    for section in sections:
        section = section.strip()
        if not section or len(section) < min_chunk_size:
            continue
        episode = _format_section_episode(section, source_file, category, formatter)
        episodes.append(episode)

    return episodes
