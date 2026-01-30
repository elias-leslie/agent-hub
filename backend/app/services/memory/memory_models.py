"""
Data models for memory service.

Defines the core types and models used throughout the memory system.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class MemorySource(str, Enum):
    """Source types for memory episodes."""

    CHAT = "chat"
    VOICE = "voice"
    SYSTEM = "system"


class MemoryScope(str, Enum):
    """Scope for memory episodes - determines visibility and retrieval context."""

    GLOBAL = "global"  # System-wide learnings (coding standards, common gotchas)
    PROJECT = "project"  # Project-specific patterns and knowledge


class MemoryCategory(str, Enum):
    """Tier-first categories for memory episodes (mandate/guardrail/reference)."""

    MANDATE = "mandate"  # Critical rules that must always be followed
    GUARDRAIL = "guardrail"  # Anti-patterns and things to avoid
    REFERENCE = "reference"  # Best practices and patterns


class MemorySearchResult(BaseModel):
    """Search result from memory system."""

    uuid: str
    content: str
    source: MemorySource
    relevance_score: float
    created_at: datetime
    facts: list[str] = []
    scope: MemoryScope | None = None
    category: MemoryCategory | None = None
    pinned: bool = False


class MemoryContext(BaseModel):
    """Context retrieved for a query."""

    query: str
    relevant_facts: list[str]
    relevant_entities: list[str]
    episodes: list[MemorySearchResult]


class MemoryEpisode(BaseModel):
    """Full episode details for listing."""

    uuid: str
    name: str
    content: str
    source: MemorySource
    category: MemoryCategory
    scope: MemoryScope = MemoryScope.GLOBAL
    scope_id: str | None = None  # project_id or task_id depending on scope
    source_description: str
    created_at: datetime
    valid_at: datetime
    entities: list[str] = []
    summary: str | None = None
    # ACE-aligned usage statistics (optional - populated when available)
    loaded_count: int | None = None
    referenced_count: int | None = None
    helpful_count: int | None = None
    harmful_count: int | None = None
    utility_score: float | None = None
    pinned: bool | None = None


class MemoryListResult(BaseModel):
    """Paginated list of episodes."""

    episodes: list[MemoryEpisode]
    total: int
    cursor: str | None = None  # Timestamp ISO string for next page
    has_more: bool


class MemoryCategoryCount(BaseModel):
    """Count for a single category."""

    category: MemoryCategory
    count: int


class MemoryScopeCount(BaseModel):
    """Count for a single scope."""

    scope: MemoryScope
    count: int


class MemoryStats(BaseModel):
    """Memory statistics for dashboard KPIs."""

    total: int
    by_category: list[MemoryCategoryCount]
    by_scope: list[MemoryScopeCount] = []
    last_updated: datetime | None
    scope: MemoryScope = MemoryScope.GLOBAL
    scope_id: str | None = None
