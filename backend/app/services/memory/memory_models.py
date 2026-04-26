"""
Data models for memory service.

Defines the core types, enums, and models used throughout the memory system.
Consolidates types from former types.py and episode_types.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class MemorySource(StrEnum):
    """Source types for memory episodes."""

    CHAT = "chat"
    VOICE = "voice"
    SYSTEM = "system"


class MemoryScope(StrEnum):
    """Scope for memory episodes - determines visibility and retrieval context."""

    GLOBAL = "global"  # System-wide learnings (coding standards, common gotchas)
    PROJECT = "project"  # Project-specific patterns and knowledge


class MemoryCategory(StrEnum):
    """Tier-first categories for memory episodes (mandate/guardrail/reference)."""

    MANDATE = "mandate"  # Critical rules that must always be followed
    GUARDRAIL = "guardrail"  # Anti-patterns and things to avoid
    REFERENCE = "reference"  # Best practices and patterns


class MemoryContextKind(StrEnum):
    """Semantic channel for a memory record."""

    POLICY = "policy"
    REFERENCE = "reference"
    CAPABILITY = "capability"
    CONTINUITY = "continuity"
    SIGNAL = "signal"


class InjectionTier(StrEnum):
    """
    Tier classification for memory episodes.

    The tier determines both categorization and injection priority:
    - MANDATE: Critical rules that must always be followed (always injected)
    - GUARDRAIL: Anti-patterns and things to avoid (high priority)
    - REFERENCE: Best practices and patterns (included if budget permits)
    """

    MANDATE = "mandate"
    GUARDRAIL = "guardrail"
    REFERENCE = "reference"


class EpisodeStatus(StrEnum):
    """
    Lifecycle status of a memory episode.

    Tracks the state of an episode through its lifecycle.
    """

    ACTIVE = "active"  # Active and eligible for injection
    ARCHIVED = "archived"  # Archived, not injected but preserved
    MERGED = "merged"  # Merged into another episode (canonical clustering)
    SUPERSEDED = "superseded"  # Replaced by a newer version


class MemoryApplicability(BaseModel):
    """Targeting rules for when a memory should be eligible."""

    consumer_profiles: list[str] = Field(default_factory=list)
    exclude_consumer_profiles: list[str] = Field(default_factory=list)
    agent_slugs: list[str] = Field(default_factory=list)
    exclude_agent_slugs: list[str] = Field(default_factory=list)
    audience_tags: list[str] = Field(default_factory=list)
    exclude_audience_tags: list[str] = Field(default_factory=list)


class MemorySearchResult(BaseModel):
    """Search result from memory system."""

    uuid: str
    content: str
    compact_content: str | None = None
    summary: str | None = None
    review_status: str = "pending"
    sensitivity_tier: str = "normal"
    last_reviewed_at: datetime | None = None
    overview: str | None = None
    rendered_content: str | None = None
    render_tier: str | None = None
    render_reason: str | None = None
    source: MemorySource
    relevance_score: float
    created_at: datetime
    facts: list[str] = []
    scope: MemoryScope | None = None
    category: MemoryCategory | None = None
    pinned: bool = False
    tags: list[str] = []
    loaded_count: int = 0
    referenced_count: int = 0
    token_count: int = 0
    confidence: float | None = None
    last_accessed_at: datetime | None = None
    source_description: str | None = None
    auto_inject: bool = False
    context_kind: MemoryContextKind = MemoryContextKind.REFERENCE
    applicability: MemoryApplicability = Field(default_factory=MemoryApplicability)

    @property
    def prompt_content(self) -> str:
        """Return the text currently selected for prompt injection."""
        return self.rendered_content or self.compact_content or self.content


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
    compact_content: str | None = None
    source: MemorySource
    category: MemoryCategory
    scope: MemoryScope = MemoryScope.GLOBAL
    scope_id: str | None = None  # project_id or task_id depending on scope
    source_description: str
    created_at: datetime
    updated_at: datetime | None = None
    version: int | None = None
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
    tags: list[str] = []
    trigger_task_types: list[str] = []
    trigger_phases: list[str] = []
    context_kind: MemoryContextKind = MemoryContextKind.REFERENCE
    applicability: MemoryApplicability = Field(default_factory=MemoryApplicability)


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


@dataclass
class FormattedEpisode:
    """Formatted episode ready for memory ingestion."""

    name: str
    episode_body: str
    source_type: str
    source_description: str
    reference_time: datetime
    group_id: str
    # Metadata for tracking
    category: MemoryCategory
    scope: MemoryScope
    tier: InjectionTier
    is_golden: bool
    is_anti_pattern: bool
    confidence: int  # 0-100
