"""
Adaptive index for memory context injection.

Implements Decision d2: Self-optimizing adaptive index that:
- Starts with ALL mandates in descriptive format (one-liner summaries)
- Learns relevance_ratio (referenced/loaded) over time
- Demotes low-ratio items after statistically significant samples
- Index size converges naturally to what's useful

The index is a compressed view of all golden standards, always injected.
It allows the LLM to understand what rules exist without full content.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from .adaptive_index_queries import fetch_mandates_with_stats
from .adaptive_index_scoring import apply_demotion, calculate_demotion_threshold
from .adaptive_index_toon import build_toon_index, generate_toon_entry

logger = logging.getLogger(__name__)

# Cache TTL for the adaptive index (default 5 minutes)
DEFAULT_INDEX_TTL_SECONDS = 300


@dataclass
class IndexEntry:
    """A single entry in the adaptive index."""

    uuid: str
    short_id: str  # First 8 chars for citation [M:uuid8]
    summary: str  # One-liner descriptive summary
    category: str  # Testing, Git, Errors, CLI, Commands, etc.
    relevance_ratio: float = 0.5  # referenced/loaded ratio
    loaded_count: int = 0
    referenced_count: int = 0
    is_demoted: bool = False  # True if below demotion threshold


@dataclass
class AdaptiveIndex:
    """The adaptive index containing all golden standard summaries."""

    entries: list[IndexEntry] = field(default_factory=list)
    last_refresh: datetime | None = None
    ttl_seconds: int = DEFAULT_INDEX_TTL_SECONDS

    # Computed demotion threshold (emerges from data distribution)
    demotion_threshold: float | None = None

    def is_stale(self, now: datetime | None = None) -> bool:
        """Check if index needs refresh."""
        if self.last_refresh is None:
            return True
        if now is None:
            now = datetime.now(UTC)
        age = (now - self.last_refresh).total_seconds()
        return age > self.ttl_seconds

    def get_active_entries(self) -> list[IndexEntry]:
        """Get non-demoted entries for injection."""
        return [e for e in self.entries if not e.is_demoted]

    def format_for_injection(self) -> str:
        """
        Format the index for context injection.

        Returns descriptive format grouped by category with citations.
        Example:
            ## Adaptive Index
            **Testing**: AAA pattern [M:abc12345], realistic data [M:def67890]
            **Git**: NEVER direct commit [M:111222333], use /commit_it [M:444555666]
        """
        if not self.entries:
            return ""

        active = self.get_active_entries()
        if not active:
            return ""

        # Group by category
        by_category: dict[str, list[IndexEntry]] = {}
        for entry in active:
            if entry.category not in by_category:
                by_category[entry.category] = []
            by_category[entry.category].append(entry)

        lines = ["## Adaptive Index"]
        for category in sorted(by_category.keys()):
            entries = by_category[category]
            items = [f"{e.summary} [M:{e.short_id}]" for e in entries]
            lines.append(f"**{category}**: {', '.join(items)}")

        return "\n".join(lines)


# Global index cache
_index_cache: AdaptiveIndex | None = None
_index_lock = asyncio.Lock()

__all__ = [
    "AdaptiveIndex",
    "IndexEntry",
    "apply_demotion",
    "build_adaptive_index",
    "build_toon_index",
    "calculate_demotion_threshold",
    "generate_toon_entry",
    "get_adaptive_index",
    "invalidate_index_cache",
    "refresh_index_if_needed",
]


async def build_adaptive_index(
    golden_standards: list[dict[str, Any]],
    usage_stats: dict[str, dict[str, int]] | None = None,
) -> AdaptiveIndex:
    """
    Build adaptive index from golden standards.

    Args:
        golden_standards: List of golden standard dicts with uuid, content, summary
        usage_stats: Optional dict of {uuid: {loaded_count, referenced_count}}

    Returns:
        AdaptiveIndex with all entries
    """
    usage_stats = usage_stats or {}

    entries: list[IndexEntry] = []

    for gs in golden_standards:
        uuid = gs.get("uuid", "")
        content = gs.get("content", "")
        summary = gs.get("summary", "")

        if not uuid or not content:
            continue

        # Get usage stats if available
        stats = usage_stats.get(uuid, {})
        loaded = stats.get("loaded_count", 0)
        referenced = stats.get("referenced_count", 0)

        # Calculate relevance ratio
        ratio = referenced / loaded if loaded > 0 else 0.5  # Default for untracked

        # Use stored summary or fallback to truncated content
        display_summary = summary if summary else content[:60].replace("\n", " ")
        if not summary and len(content) > 60:
            display_summary = display_summary.rsplit(" ", 1)[0] + "..."

        entry = IndexEntry(
            uuid=uuid,
            short_id=uuid[:8],
            summary=display_summary,
            category="General",
            relevance_ratio=ratio,
            loaded_count=loaded,
            referenced_count=referenced,
        )
        entries.append(entry)

    # Calculate and apply demotion threshold
    threshold = calculate_demotion_threshold(entries)
    entries = apply_demotion(entries, threshold)

    index = AdaptiveIndex(
        entries=entries,
        last_refresh=datetime.now(UTC),
        demotion_threshold=threshold,
    )

    logger.info(
        "Built adaptive index: %d entries, %d active, threshold=%.3f",
        len(entries),
        len(index.get_active_entries()),
        threshold or 0.0,
    )

    return index


async def get_adaptive_index(
    force_refresh: bool = False,
) -> AdaptiveIndex:
    """
    Get the adaptive index, building/refreshing as needed.

    Uses caching with TTL to avoid frequent Neo4j queries.

    Args:
        force_refresh: Force rebuild even if cache is fresh

    Returns:
        Current AdaptiveIndex
    """
    global _index_cache

    async with _index_lock:
        if _index_cache is not None and not force_refresh and not _index_cache.is_stale():
            return _index_cache

        golden, usage_stats = await fetch_mandates_with_stats()

        if not golden and _index_cache is not None:
            return _index_cache  # Return stale cache on error

        _index_cache = await build_adaptive_index(golden, usage_stats)
        return _index_cache


async def invalidate_index_cache() -> None:
    """Invalidate the index cache, forcing rebuild on next access."""
    global _index_cache
    async with _index_lock:
        _index_cache = None
        logger.info("Adaptive index cache invalidated")


async def refresh_index_if_needed(
    utility_score_changes: dict[str, float] | None = None,
    change_threshold: float = 0.1,
) -> bool:
    """
    Refresh index if utility scores have changed significantly.

    Args:
        utility_score_changes: Dict of {uuid: score_change}
        change_threshold: Minimum change to trigger refresh

    Returns:
        True if index was refreshed
    """
    if utility_score_changes:
        significant_changes = [
            c for c in utility_score_changes.values() if abs(c) >= change_threshold
        ]
        if significant_changes:
            await invalidate_index_cache()
            await get_adaptive_index(force_refresh=True)
            return True

    return False
