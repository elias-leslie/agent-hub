"""
Shared type definitions for the memory subsystem.

This module defines the canonical type hierarchy for memory episodes:
- EpisodeType: What kind of knowledge the episode represents
- InjectionTier: Priority level for context injection (budget allocation)
- EpisodeStatus: Lifecycle state of an episode
"""

from enum import Enum


class EpisodeType(str, Enum):
    """
    Type of knowledge stored in a memory episode.

    Used for categorization and retrieval filtering.
    """

    MANDATE = "mandate"  # Critical rules that must always be followed
    GUARDRAIL = "guardrail"  # Anti-patterns and things to avoid
    PATTERN = "pattern"  # Recommended patterns and best practices
    DISCOVERY = "discovery"  # Learned facts about the codebase
    GOTCHA = "gotcha"  # Known pitfalls and edge cases
    SESSION = "session"  # Session-specific context
    TASK = "task"  # Task-specific context


class InjectionTier(str, Enum):
    """
    Priority tier for context injection budget allocation.

    Episodes are injected in priority order until budget is exhausted:
    - ALWAYS: Always included regardless of budget
    - HIGH: Included first from the budget
    - MEDIUM: Included if budget permits after HIGH
    - LOW: Included only if significant budget remains
    - NEVER: Never injected (archived/disabled)
    """

    ALWAYS = "always"  # Always inject (critical constraints)
    HIGH = "high"  # High priority, inject first from budget
    MEDIUM = "medium"  # Medium priority
    LOW = "low"  # Low priority, only if budget permits
    NEVER = "never"  # Never inject (disabled/archived)


class EpisodeStatus(str, Enum):
    """
    Lifecycle status of a memory episode.

    Tracks the state of an episode through its lifecycle.
    """

    ACTIVE = "active"  # Active and eligible for injection
    ARCHIVED = "archived"  # Archived, not injected but preserved
    MERGED = "merged"  # Merged into another episode (canonical clustering)
    SUPERSEDED = "superseded"  # Replaced by a newer version
