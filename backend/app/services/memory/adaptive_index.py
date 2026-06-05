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
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from .adaptive_index_models import AdaptiveIndex, IndexEntry, build_index_entry
from .adaptive_index_queries import fetch_mandates_with_stats
from .adaptive_index_scoring import apply_demotion, calculate_demotion_threshold
from .adaptive_index_toon import build_toon_index, generate_toon_entry

logger = logging.getLogger(__name__)

# Cache TTL for the adaptive index (default 5 minutes)
DEFAULT_INDEX_TTL_SECONDS = 300

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
]


async def build_adaptive_index(
    golden_standards: list[dict[str, str]],
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
    resolved_stats = usage_stats or {}

    entries: list[IndexEntry] = []
    for gs in golden_standards:
        entry = build_index_entry(gs, resolved_stats)
        if entry is not None:
            entries.append(entry)

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
    db: AsyncSession | None = None,
) -> AdaptiveIndex:
    """
    Get the adaptive index, building/refreshing as needed.

    Uses caching with TTL to avoid frequent database queries.

    Args:
        force_refresh: Force rebuild even if cache is fresh

    Returns:
        Current AdaptiveIndex
    """
    global _index_cache

    async with _index_lock:
        if _index_cache is not None and not force_refresh and not _index_cache.is_stale():
            return _index_cache

        golden, fetched_stats = await fetch_mandates_with_stats(db=db)

        if not golden and _index_cache is not None:
            return _index_cache  # Return stale cache on error

        _index_cache = await build_adaptive_index(golden, fetched_stats)
        return _index_cache
