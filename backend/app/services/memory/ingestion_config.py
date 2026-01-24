"""
Ingestion configuration profiles for the EpisodeCreator.

Defines presets for different ingestion scenarios with appropriate
validation, deduplication, and tier settings.
"""

from dataclasses import dataclass

from .types import EpisodeType, InjectionTier


@dataclass
class IngestionConfig:
    """
    Configuration for episode ingestion behavior.

    Attributes:
        validate: Whether to validate content (reject verbose/conversational)
        deduplicate: Whether to check for duplicate content
        dedup_window_minutes: Time window for deduplication (0 = no window)
        episode_type: Type of episode being created
        tier: Injection priority tier
        is_golden: Whether this is a golden standard (highest confidence)
    """

    validate: bool = True
    deduplicate: bool = True
    dedup_window_minutes: int = 5
    episode_type: EpisodeType = EpisodeType.PATTERN
    tier: InjectionTier = InjectionTier.MEDIUM
    is_golden: bool = False


# Predefined ingestion profiles

GOLDEN_STANDARD = IngestionConfig(
    validate=True,
    deduplicate=True,
    dedup_window_minutes=0,  # No time window - always check
    episode_type=EpisodeType.MANDATE,
    tier=InjectionTier.ALWAYS,
    is_golden=True,
)
"""Profile for golden standards: highest confidence, always injected."""

CHAT_STREAM = IngestionConfig(
    validate=False,
    deduplicate=True,
    dedup_window_minutes=1,  # Short window for real-time chat
    episode_type=EpisodeType.SESSION,
    tier=InjectionTier.LOW,
    is_golden=False,
)
"""Profile for chat/stream content: minimal validation, short dedup window."""

LEARNING = IngestionConfig(
    validate=True,
    deduplicate=True,
    dedup_window_minutes=5,
    episode_type=EpisodeType.PATTERN,
    tier=InjectionTier.MEDIUM,
    is_golden=False,
)
"""Profile for runtime learnings: standard validation and dedup."""

TOOL_DISCOVERY = IngestionConfig(
    validate=True,
    deduplicate=True,
    dedup_window_minutes=5,
    episode_type=EpisodeType.DISCOVERY,
    tier=InjectionTier.MEDIUM,
    is_golden=False,
)
"""Profile for tool discoveries: facts learned about the codebase."""

TOOL_GOTCHA = IngestionConfig(
    validate=True,
    deduplicate=True,
    dedup_window_minutes=5,
    episode_type=EpisodeType.GOTCHA,
    tier=InjectionTier.HIGH,
    is_golden=False,
)
"""Profile for gotchas/pitfalls: high priority to prevent repeated mistakes."""
