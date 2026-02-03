"""
EpisodeCreator - Single entry point for all Graphiti episode creation.

This module implements the "single funnel" pattern for memory ingestion:
- All episode creation flows through EpisodeCreator.create()
- Validation, deduplication, and budget checks happen here
- Only one place in the codebase calls Graphiti.add_episode directly
- Batch creation with token-aware packing for efficient embedding API usage
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache

from graphiti_core.utils.datetime_utils import utc_now

from .episode_creator_batch_processor import batch_create_episodes
from .episode_creator_core import create_episode_internal
from .episode_creator_models import (
    BatchCreateResult,
    BatchEpisodeRequest,
    CreateResult,
)
from .graphiti_client import get_graphiti
from .ingestion_config import LEARNING, IngestionConfig
from .service import MemoryScope, MemorySource, build_group_id


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
            summary: Optional summary for the episode

        Returns:
            CreateResult with success status, UUID if created, or error info
        """
        config = config or LEARNING
        reference_time = reference_time or utc_now()

        return await create_episode_internal(
            graphiti=self._graphiti,
            group_id=self._group_id,
            content=content,
            name=name,
            config=config,
            source_description=source_description,
            reference_time=reference_time,
            injection_tier=injection_tier,
            summary=summary,
        )

    async def batch_create(
        self,
        episodes: list[BatchEpisodeRequest],
        *,
        max_tokens: int | None = None,
        concurrency: int | None = None,
    ) -> BatchCreateResult:
        """
        Create multiple episodes with token-aware batch packing.

        Episodes are packed into batches respecting the token limit,
        then batches are processed concurrently up to the concurrency limit.

        This optimizes embedding API usage by:
        - Packing episodes to maximize tokens per batch (reduce API calls)
        - Processing batches concurrently (reduce total time)
        - Respecting rate limits via concurrency control

        Args:
            episodes: List of BatchEpisodeRequest to create
            max_tokens: Max tokens per batch (default: EMBEDDING_BATCH_MAX_TOKENS)
            concurrency: Max concurrent batches (default: EMBEDDING_BATCH_CONCURRENCY)

        Returns:
            BatchCreateResult with individual results and summary statistics
        """
        return await batch_create_episodes(
            self,
            episodes,
            max_tokens=max_tokens,
            concurrency=concurrency,
        )


@lru_cache
def get_episode_creator(
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
) -> EpisodeCreator:
    """Get cached EpisodeCreator instance for a scope."""
    return EpisodeCreator(scope=scope, scope_id=scope_id)
