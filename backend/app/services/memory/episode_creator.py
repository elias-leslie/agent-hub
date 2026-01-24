"""
EpisodeCreator - Single entry point for all Graphiti episode creation.

This module implements the "single funnel" pattern for memory ingestion:
- All episode creation flows through EpisodeCreator.create()
- Validation, deduplication, and budget checks happen here
- Only one place in the codebase calls Graphiti.add_episode directly
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache

from graphiti_core.nodes import EpisodeType as GraphitiEpisodeType
from graphiti_core.utils.datetime_utils import utc_now

from .dedup import content_hash, find_exact_duplicate
from .graphiti_client import get_graphiti
from .ingestion_config import LEARNING, IngestionConfig
from .service import MemoryScope, MemorySource, build_group_id

logger = logging.getLogger(__name__)


# Verbose patterns that indicate conversational/verbose content
VERBOSE_PATTERNS = [
    "you should",
    "i recommend",
    "please",
    "thank you",
    "let me know",
    "feel free",
    "i suggest",
    "you might want",
    "consider using",
    "it would be",
    "it's important to",
]


@dataclass
class CreateResult:
    """Result of an episode creation attempt."""

    success: bool
    uuid: str | None = None
    deduplicated: bool = False
    validation_error: str | None = None


class EpisodeCreator:
    """
    Single entry point for all Graphiti episode creation.

    Usage:
        creator = get_episode_creator()
        result = await creator.create(
            content="Important pattern to remember",
            name="pattern_name",
            config=GOLDEN_STANDARD,
        )
        if result.success:
            print(f"Created episode: {result.uuid}")
        elif result.deduplicated:
            print("Content was a duplicate, skipped")
        else:
            print(f"Validation failed: {result.validation_error}")
    """

    def __init__(
        self,
        scope: MemoryScope = MemoryScope.GLOBAL,
        scope_id: str | None = None,
    ):
        self.scope = scope
        self.scope_id = scope_id
        self._group_id = build_group_id(scope, scope_id)
        self._graphiti = get_graphiti()

    async def create(
        self,
        content: str,
        name: str,
        config: IngestionConfig | None = None,
        *,
        source_description: str | None = None,
        reference_time: datetime | None = None,
        source: MemorySource = MemorySource.SYSTEM,
    ) -> CreateResult:
        """
        Create a new episode in the knowledge graph.

        This is the ONLY method that should call Graphiti.add_episode.

        Args:
            content: The episode content/body
            name: Episode name (slug-like identifier)
            config: Ingestion configuration (defaults to LEARNING profile)
            source_description: Human-readable source description
            reference_time: When the episode occurred (defaults to now)
            source: Source type for the episode

        Returns:
            CreateResult with success status, UUID if created, or error info
        """
        config = config or LEARNING
        reference_time = reference_time or utc_now()

        # Step 1: Validate content if configured
        if config.validate:
            validation_error = self._validate_content(content)
            if validation_error:
                return CreateResult(
                    success=False,
                    validation_error=validation_error,
                )

        # Step 2: Check for duplicates if configured
        if config.deduplicate:
            duplicate = await self._find_duplicate(content, config.dedup_window_minutes)
            if duplicate:
                logger.debug("Skipping duplicate content: %s", content[:50])
                return CreateResult(
                    success=True,
                    uuid=duplicate,
                    deduplicated=True,
                )

        # Step 3: Build source description with metadata
        if not source_description:
            source_description = self._build_source_description(config)

        # Step 4: Create the episode via Graphiti
        # THIS IS THE ONLY PLACE THAT CALLS graphiti.add_episode
        try:
            result = await self._graphiti.add_episode(
                name=name,
                episode_body=content,
                source=GraphitiEpisodeType.text,
                source_description=source_description,
                reference_time=reference_time,
                group_id=self._group_id,
            )

            logger.info(
                "Created episode %s: %d entities, %d edges",
                result.episode.uuid,
                len(result.nodes),
                len(result.edges),
            )

            return CreateResult(
                success=True,
                uuid=result.episode.uuid,
            )

        except Exception as e:
            logger.error("Failed to create episode: %s", e)
            return CreateResult(
                success=False,
                validation_error=f"Graphiti error: {e}",
            )

    def _validate_content(self, content: str) -> str | None:
        """
        Validate episode content for conciseness and declarative style.

        Returns error message if invalid, None if valid.
        """
        content_lower = content.lower()
        detected = []

        for pattern in VERBOSE_PATTERNS:
            if pattern in content_lower:
                detected.append(pattern)

        if detected:
            return (
                f"Content is too verbose. Write declarative facts, not conversational advice. "
                f"Detected patterns: {', '.join(repr(p) for p in detected)}"
            )

        return None

    async def _find_duplicate(self, content: str, window_minutes: int) -> str | None:
        """
        Check for duplicate content within the dedup window.

        Uses SHA256 hash-based exact duplicate detection.

        Returns the UUID of the existing episode if found, None otherwise.
        """
        # Use hash-based deduplication
        return await find_exact_duplicate(content, window_minutes)

    def _get_content_hash(self, content: str) -> str:
        """Get SHA256 hash of content for deduplication."""
        return content_hash(content)

    def _build_source_description(self, config: IngestionConfig) -> str:
        """Build source description with metadata."""
        parts = [
            config.episode_type.value,
            f"tier:{config.tier.value}",
        ]
        if config.is_golden:
            parts.append("source:golden_standard")
            parts.append("confidence:100")
        return " ".join(parts)


# Module-level singleton
_creator: EpisodeCreator | None = None


@lru_cache
def get_episode_creator(
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
) -> EpisodeCreator:
    """Get cached EpisodeCreator instance for a scope."""
    return EpisodeCreator(scope=scope, scope_id=scope_id)
