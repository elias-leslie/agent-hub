"""
Data models for adaptive index.

Defines IndexEntry and AdaptiveIndex dataclasses, plus helpers
for constructing entries from golden standard dicts.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

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
            **Git**: NEVER direct commit [M:111222333], use commit.sh [M:444555666]
        """
        if not self.entries:
            return ""

        active = self.get_active_entries()
        if not active:
            return ""

        by_category: dict[str, list[IndexEntry]] = {}
        for entry in active:
            by_category.setdefault(entry.category, []).append(entry)

        lines = ["## Adaptive Index"]
        for category in sorted(by_category.keys()):
            items = [f"{e.summary} [M:{e.short_id}]" for e in by_category[category]]
            lines.append(f"**{category}**: {', '.join(items)}")

        return "\n".join(lines)


def build_index_entry(
    gs: dict[str, str],
    usage_stats: dict[str, dict[str, int]],
) -> IndexEntry | None:
    """
    Build a single IndexEntry from a golden standard dict.

    Returns None if the entry is invalid (missing uuid or content).
    """
    uuid = gs.get("uuid", "")
    content = gs.get("content", "")
    summary = gs.get("summary", "")

    if not uuid or not content:
        return None

    stats = usage_stats.get(uuid, {})
    loaded = stats.get("loaded_count", 0)
    referenced = stats.get("referenced_count", 0)
    ratio = referenced / loaded if loaded > 0 else 0.5

    display_summary = summary if summary else content[:60].replace("\n", " ")
    if not summary and len(content) > 60:
        display_summary = display_summary.rsplit(" ", 1)[0] + "..."

    return IndexEntry(
        uuid=uuid,
        short_id=uuid[:8],
        summary=display_summary,
        category="General",
        relevance_ratio=ratio,
        loaded_count=loaded,
        referenced_count=referenced,
    )
