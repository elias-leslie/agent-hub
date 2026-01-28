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
import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

# Cache TTL for the adaptive index (default 5 minutes)
DEFAULT_INDEX_TTL_SECONDS = 300

# Minimum samples required before demotion is considered
# Uses confidence interval approach: need enough data for statistical significance
MIN_SAMPLES_FOR_DEMOTION = 10


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


def calculate_demotion_threshold(entries: list[IndexEntry]) -> float | None:
    """
    Calculate dynamic demotion threshold from data distribution.

    Implements: median(all_ratios) - 1_stdev
    Threshold emerges from data, not hardcoded.

    Args:
        entries: List of index entries with usage stats

    Returns:
        Threshold value, or None if insufficient data
    """
    # Need entries with sufficient samples
    eligible = [e for e in entries if e.loaded_count >= MIN_SAMPLES_FOR_DEMOTION]

    if len(eligible) < 3:
        # Not enough data for statistical analysis
        return None

    ratios = [e.relevance_ratio for e in eligible]

    try:
        median = statistics.median(ratios)
        stdev = statistics.stdev(ratios) if len(ratios) > 1 else 0
        threshold = median - stdev

        # Don't allow negative threshold
        return max(0.0, threshold)
    except statistics.StatisticsError:
        return None


def apply_demotion(
    entries: list[IndexEntry],
    threshold: float | None,
) -> list[IndexEntry]:
    """
    Apply demotion logic to entries based on relevance ratio.

    Entries below threshold AND with sufficient samples are demoted.

    Args:
        entries: List of index entries
        threshold: Dynamic demotion threshold

    Returns:
        Updated entries with is_demoted set
    """
    if threshold is None:
        # No threshold calculated yet, don't demote anything
        return entries

    for entry in entries:
        # Only demote if we have statistically significant data
        if entry.loaded_count >= MIN_SAMPLES_FOR_DEMOTION:
            entry.is_demoted = entry.relevance_ratio < threshold
        else:
            entry.is_demoted = False

    return entries


def categorize_content(content: str) -> str:
    """
    Infer category from content keywords.

    Categories: Testing, Git, Errors, CLI, Commands, Coding, Architecture
    """
    content_lower = content.lower()

    if any(kw in content_lower for kw in ["test", "pytest", "mock", "fixture", "aaa"]):
        return "Testing"
    if any(kw in content_lower for kw in ["git", "commit", "push", "branch", "merge"]):
        return "Git"
    if any(kw in content_lower for kw in ["error", "exception", "fail", "bug"]):
        return "Errors"
    if any(kw in content_lower for kw in ["cli", "command", "terminal", "bash"]):
        return "CLI"
    if any(kw in content_lower for kw in ["/", "st ", "dt ", "slash"]):
        return "Commands"
    if any(kw in content_lower for kw in ["async", "await", "function", "class"]):
        return "Coding"
    if any(kw in content_lower for kw in ["architect", "design", "pattern", "system"]):
        return "Architecture"

    return "General"


def summarize_content(content: str, max_length: int = 60) -> str:
    """
    Create a one-liner summary from content.

    Takes first sentence or truncates to max_length.
    """
    # Remove newlines
    content = content.replace("\n", " ").strip()

    # Try to get first sentence
    for delim in [".", "!", "?"]:
        if delim in content:
            first_sentence = content.split(delim)[0].strip()
            if len(first_sentence) <= max_length:
                return first_sentence
            break

    # Truncate if needed
    if len(content) > max_length:
        return content[: max_length - 3].rsplit(" ", 1)[0] + "..."

    return content


async def build_adaptive_index(
    golden_standards: list[dict[str, Any]],
    usage_stats: dict[str, dict[str, int]] | None = None,
) -> AdaptiveIndex:
    """
    Build adaptive index from golden standards.

    Args:
        golden_standards: List of golden standard dicts with uuid, content
        usage_stats: Optional dict of {uuid: {loaded_count, referenced_count}}

    Returns:
        AdaptiveIndex with all entries
    """
    usage_stats = usage_stats or {}

    entries: list[IndexEntry] = []

    for gs in golden_standards:
        uuid = gs.get("uuid", "")
        content = gs.get("content", "")

        if not uuid or not content:
            continue

        # Get usage stats if available
        stats = usage_stats.get(uuid, {})
        loaded = stats.get("loaded_count", 0)
        referenced = stats.get("referenced_count", 0)

        # Calculate relevance ratio
        ratio = referenced / loaded if loaded > 0 else 0.5  # Default for untracked

        entry = IndexEntry(
            uuid=uuid,
            short_id=uuid[:8],
            summary=summarize_content(content),
            category=categorize_content(content),
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

        # Fetch mandates directly from Neo4j
        from .graphiti_client import get_graphiti

        try:
            graphiti = get_graphiti()
            driver = graphiti.driver
            query = """
            MATCH (e:Episodic {group_id: 'global'})
            WHERE e.injection_tier = 'mandate'
            RETURN e.uuid AS uuid, e.content AS content, e.source_description AS source_description,
                   COALESCE(e.loaded_count, 0) AS loaded_count, COALESCE(e.referenced_count, 0) AS referenced_count,
                   COALESCE(e.utility_score, 0.5) AS utility_score
            """
            records, _, _ = await driver.execute_query(query)
            golden = [dict(r) for r in records]
        except Exception as e:
            logger.error("Failed to fetch mandates: %s", e)
            if _index_cache is not None:
                return _index_cache  # Return stale cache on error
            return AdaptiveIndex()  # Empty index

        # Build usage stats from the query results
        usage_stats = {
            g["uuid"]: {
                "loaded_count": g["loaded_count"],
                "referenced_count": g["referenced_count"],
            }
            for g in golden
            if g.get("uuid")
        }

        _index_cache = await build_adaptive_index(golden, usage_stats)
        return _index_cache


async def _fetch_usage_stats(uuids: list[str]) -> dict[str, dict[str, int]]:
    """
    Fetch usage statistics for given UUIDs from Neo4j.

    Returns dict of {uuid: {loaded_count, referenced_count}}
    """
    if not uuids:
        return {}

    try:
        from .graphiti_client import get_graphiti

        graphiti = get_graphiti()
        driver = graphiti.driver

        query = """
        MATCH (e:Episodic)
        WHERE e.uuid IN $uuids
        RETURN e.uuid AS uuid,
               COALESCE(e.loaded_count, 0) AS loaded_count,
               COALESCE(e.referenced_count, 0) AS referenced_count
        """

        records, _, _ = await driver.execute_query(query, uuids=uuids)

        return {
            r["uuid"]: {
                "loaded_count": r["loaded_count"],
                "referenced_count": r["referenced_count"],
            }
            for r in records
        }
    except Exception as e:
        logger.warning("Failed to fetch usage stats: %s", e)
        return {}


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
