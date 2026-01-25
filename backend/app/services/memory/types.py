"""
Shared type definitions for the memory subsystem.

This module defines the canonical type hierarchy for memory episodes:
- InjectionTier: What tier the episode belongs to (mandate/guardrail/reference)
- EpisodeStatus: Lifecycle state of an episode
"""

from enum import Enum


class InjectionTier(str, Enum):
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


class EpisodeStatus(str, Enum):
    """
    Lifecycle status of a memory episode.

    Tracks the state of an episode through its lifecycle.
    """

    ACTIVE = "active"  # Active and eligible for injection
    ARCHIVED = "archived"  # Archived, not injected but preserved
    MERGED = "merged"  # Merged into another episode (canonical clustering)
    SUPERSEDED = "superseded"  # Replaced by a newer version
