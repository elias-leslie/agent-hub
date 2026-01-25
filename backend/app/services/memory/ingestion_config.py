"""
Ingestion configuration profiles for the EpisodeCreator.

Defines presets for different ingestion scenarios with appropriate
validation, deduplication, and tier settings.
"""

from dataclasses import dataclass

from .types import InjectionTier


@dataclass
class IngestionConfig:
    """
    Configuration for episode ingestion behavior.

    Attributes:
        validate: Whether to validate content (reject verbose/conversational)
        deduplicate: Whether to check for duplicate content
        dedup_window_minutes: Time window for deduplication (0 = no window)
        tier: Injection tier (mandate/guardrail/reference)
        is_golden: Whether this is a golden standard (highest confidence)
    """

    validate: bool = True
    deduplicate: bool = True
    dedup_window_minutes: int = 5
    tier: InjectionTier = InjectionTier.REFERENCE
    is_golden: bool = False


# Predefined ingestion profiles

GOLDEN_STANDARD = IngestionConfig(
    validate=True,
    deduplicate=True,
    dedup_window_minutes=0,
    tier=InjectionTier.MANDATE,
    is_golden=True,
)
"""Profile for golden standards: highest confidence, always injected."""

CHAT_STREAM = IngestionConfig(
    validate=False,
    deduplicate=True,
    dedup_window_minutes=1,
    tier=InjectionTier.REFERENCE,
    is_golden=False,
)
"""Profile for chat/stream content: minimal validation, short dedup window."""

LEARNING = IngestionConfig(
    validate=True,
    deduplicate=True,
    dedup_window_minutes=5,
    tier=InjectionTier.REFERENCE,
    is_golden=False,
)
"""Profile for runtime learnings: standard validation and dedup."""

TOOL_DISCOVERY = IngestionConfig(
    validate=True,
    deduplicate=True,
    dedup_window_minutes=5,
    tier=InjectionTier.REFERENCE,
    is_golden=False,
)
"""Profile for tool discoveries: facts learned about the codebase."""

TOOL_GOTCHA = IngestionConfig(
    validate=True,
    deduplicate=True,
    dedup_window_minutes=5,
    tier=InjectionTier.GUARDRAIL,
    is_golden=False,
)
"""Profile for gotchas/pitfalls: high priority to prevent repeated mistakes."""
