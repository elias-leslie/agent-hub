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

from .budget import count_tokens
from .dedup import content_hash, find_exact_duplicate
from .graphiti_client import (
    get_graphiti,
    init_episode_usage_properties,
    set_episode_injection_tier,
)
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
    "remember",
    "make sure",
    "note:",
    "important:",
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
        injection_tier: str | None = None,
        summary: str | None = None,
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
            injection_tier: Explicit tier override (mandate/guardrail/reference).
                           If None, derived from config.tier.

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

            episode_uuid = result.episode.uuid
            logger.info(
                "Created episode %s: %d entities, %d edges",
                episode_uuid,
                len(result.nodes),
                len(result.edges),
            )

            # Step 5: Set injection_tier on the Neo4j node
            tier = injection_tier or self._derive_injection_tier(config)
            if tier:
                await set_episode_injection_tier(episode_uuid, tier)

            # Step 5b: Set summary if provided
            if summary:
                from app.services.memory.graphiti_client import set_episode_summary

                await set_episode_summary(episode_uuid, summary)

            # Step 6: Initialize usage tracking properties (loaded_count=0, referenced_count=0)
            await init_episode_usage_properties(episode_uuid)

            # Step 7: Set token_count for utility-per-token scoring
            token_count = count_tokens(content)
            await self._set_token_count(episode_uuid, token_count)

            return CreateResult(
                success=True,
                uuid=episode_uuid,
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
            f"tier:{config.tier.value}",
        ]
        return " ".join(parts)

    def _derive_injection_tier(self, config: IngestionConfig) -> str:
        """Derive injection_tier from config settings."""
        if config.is_golden:
            return "mandate"
        tier_value = config.tier.value
        if tier_value in ("always", "mandate"):
            return "mandate"
        if tier_value in ("high", "guardrail"):
            return "guardrail"
        return "reference"

    async def _set_token_count(self, episode_uuid: str, token_count: int) -> bool:
        """Set token_count property on an Episodic node."""
        query = """
        MATCH (e:Episodic {uuid: $uuid})
        SET e.token_count = $token_count
        RETURN e.uuid AS uuid
        """
        try:
            records, _, _ = await self._graphiti.driver.execute_query(
                query,
                uuid=episode_uuid,
                token_count=token_count,
            )
            return bool(records)
        except Exception as e:
            logger.warning("Failed to set token_count for %s: %s", episode_uuid[:8], e)
            return False


# Module-level singleton
_creator: EpisodeCreator | None = None


@lru_cache
def get_episode_creator(
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
) -> EpisodeCreator:
    """Get cached EpisodeCreator instance for a scope."""
    return EpisodeCreator(scope=scope, scope_id=scope_id)
