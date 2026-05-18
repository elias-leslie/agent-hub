"""
EpisodeCreator - Single entry point for all memory episode creation.

This module implements the "single funnel" pattern for memory ingestion:
- All episode creation flows through EpisodeCreator.create()
- Validation, deduplication, and budget checks happen here
- Only one place in the codebase inserts memories into PostgreSQL
- Batch creation with token-aware packing for efficient embedding API usage
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime
from functools import lru_cache

from .budget import count_tokens
from .dedup import find_exact_duplicate
from .embedder import EmbedderService, get_embedder
from .episode_creator_helpers import (
    build_source_quality_metadata,
    handle_rate_limit_error,
    insert_memory,
    is_rate_limit_error,
    validate_content,
)
from .episode_creator_models import (
    BatchCreateResult,
    BatchEpisodeRequest,
    CreateResult,
)
from .episode_helpers import (
    build_simple_source_description,
    derive_injection_tier,
)
from .ingestion_config import LEARNING, IngestionConfig
from .repository import TIER_MAP, MemoryRepository, get_memory_repository
from .service import MemoryScope, MemorySource, build_group_id

logger = logging.getLogger(__name__)

VERBOSE_PATTERNS = [
    "memory_retrieval",
    "memory_storage",
    "embedding_generation",
    "cache_hit",
    "cache_miss",
]

# Gemini embedding limit is ~8K tokens.
EMBEDDING_BATCH_MAX_TOKENS = int(os.environ.get("EMBEDDING_BATCH_MAX_TOKENS", "8000"))
EMBEDDING_BATCH_CONCURRENCY = int(os.environ.get("EMBEDDING_BATCH_CONCURRENCY", "4"))


async def _check_duplicate(
    content: str, config: IngestionConfig
) -> CreateResult | None:
    """Return a deduplicated CreateResult if duplicate found, else None."""
    if not config.deduplicate:
        return None
    duplicate = await find_exact_duplicate(content, config.dedup_window_minutes)
    if duplicate:
        logger.debug("Skipping duplicate content: %s", content[:50])
        return CreateResult(success=True, uuid=duplicate, deduplicated=True)
    return None


async def _create_and_finalize(
    repo: MemoryRepository,
    embedder: EmbedderService,
    group_id: str,
    content: str,
    name: str,
    source_description: str,
    reference_time: datetime,
    config: IngestionConfig,
    injection_tier: str | None,
    context_kind: str | None,
    applicability: dict[str, object] | None,
    tags: list[str] | None,
    summary: str | None,
    metadata: dict[str, object] | None,
    sensitivity_tier: str,
    changed_by: str | None,
    change_reason: str | None,
) -> CreateResult:
    """Embed content, insert into PostgreSQL, and return result."""
    try:
        embedding = await embedder.embed(content)
        tier_name = injection_tier or derive_injection_tier(config)
        tier_num = TIER_MAP.get(tier_name, 3)
        token_count_value = count_tokens(content)
        episode_uuid = await insert_memory(
            repo,
            content=content,
            name=name,
            group_id=group_id,
            source_description=source_description,
            reference_time=reference_time,
            embedding=embedding,
            context_kind=context_kind,
            applicability=applicability,
            tags=tags,
            tier=tier_num,
            summary=summary,
            metadata=metadata,
            sensitivity_tier=sensitivity_tier,
            token_count=token_count_value,
            changed_by=changed_by,
            change_reason=change_reason,
        )
        logger.info(
            "Created memory %s (tier=%s, tokens=%d)",
            episode_uuid,
            tier_name,
            token_count_value,
        )
        return CreateResult(success=True, uuid=episode_uuid)
    except Exception as e:
        if is_rate_limit_error(e):
            return handle_rate_limit_error(e)
        logger.error("Failed to create memory: %s", e)
        return CreateResult(success=False, validation_error=f"Memory creation error: {e}")


async def create_episode_internal(
    repo: MemoryRepository,
    embedder: EmbedderService,
    group_id: str,
    content: str,
    name: str,
    config: IngestionConfig,
    source_description: str | None,
    reference_time: datetime,
    injection_tier: str | None,
    context_kind: str | None,
    applicability: dict[str, object] | None,
    tags: list[str] | None,
    summary: str | None,
    metadata: dict[str, object] | None,
    sensitivity_tier: str,
    changed_by: str | None,
    change_reason: str | None,
    bypass_compactness: bool = False,
) -> CreateResult:
    """Internal implementation of episode creation."""
    if (result := validate_content(content, config, bypass_compactness=bypass_compactness)) is not None:
        return result

    if (result := await _check_duplicate(content, config)) is not None:
        return result

    if not source_description:
        source_description = build_simple_source_description(config)

    tier_name = injection_tier or derive_injection_tier(config)
    if config.validate:
        metadata = build_source_quality_metadata(
            content,
            metadata,
            checked_at=reference_time,
            tier_name=tier_name,
        )

    return await _create_and_finalize(
        repo,
        embedder,
        group_id,
        content,
        name,
        source_description,
        reference_time,
        config,
        tier_name,
        context_kind,
        applicability,
        tags,
        summary,
        metadata,
        sensitivity_tier,
        changed_by,
        change_reason,
    )


def pack_episodes_into_batches(
    episodes: list[BatchEpisodeRequest],
    max_tokens: int = EMBEDDING_BATCH_MAX_TOKENS,
) -> list[list[BatchEpisodeRequest]]:
    """Pack episodes into token-aware batches via first-fit decreasing.

    Episodes exceeding max_tokens are placed in their own batch.
    """
    if not episodes:
        return []

    sorted_episodes = sorted(episodes, key=lambda e: e.token_count, reverse=True)

    batches: list[list[BatchEpisodeRequest]] = []
    batch_tokens: list[int] = []

    for episode in sorted_episodes:
        tokens = episode.token_count
        placed = False

        for i, batch in enumerate(batches):
            if batch_tokens[i] + tokens <= max_tokens:
                batch.append(episode)
                batch_tokens[i] += tokens
                placed = True
                break

        if not placed:
            batches.append([episode])
            batch_tokens.append(tokens)

    return batches


async def _process_batches(
    creator: EpisodeCreator,
    batches: list[list[BatchEpisodeRequest]],
    concurrency: int,
) -> list[CreateResult]:
    """Process batches with controlled concurrency."""
    semaphore = asyncio.Semaphore(concurrency)
    all_results: list[CreateResult] = []

    async def process_batch(batch: list[BatchEpisodeRequest]) -> list[CreateResult]:
        async with semaphore:
            batch_results = []
            for ep in batch:
                result = await creator.create(
                    content=ep.content,
                    name=ep.name,
                    config=ep.config,
                    source_description=ep.source_description,
                    reference_time=ep.reference_time,
                    source=ep.source,
                    injection_tier=ep.injection_tier,
                    context_kind=ep.context_kind,
                    applicability=ep.applicability,
                    tags=ep.tags,
                    summary=ep.summary,
                    metadata=ep.metadata,
                )
                batch_results.append(result)
            return batch_results

    batch_tasks = [process_batch(batch) for batch in batches]
    batch_results = await asyncio.gather(*batch_tasks)

    for batch_result in batch_results:
        all_results.extend(batch_result)

    return all_results


async def batch_create_episodes(
    creator: EpisodeCreator,
    episodes: list[BatchEpisodeRequest],
    *,
    max_tokens: int | None = None,
    concurrency: int | None = None,
) -> BatchCreateResult:
    """Create multiple episodes with token-aware batch packing.

    Episodes are packed respecting the token limit, then processed concurrently.
    """
    if not episodes:
        return BatchCreateResult()

    max_tokens = max_tokens or EMBEDDING_BATCH_MAX_TOKENS
    concurrency = concurrency or EMBEDDING_BATCH_CONCURRENCY

    batches = pack_episodes_into_batches(episodes, max_tokens)

    logger.info(
        "Batch creating %d episodes in %d batches (max %d tokens/batch, %d concurrent)",
        len(episodes),
        len(batches),
        max_tokens,
        concurrency,
    )

    all_results = await _process_batches(creator, batches, concurrency)

    successful = sum(1 for r in all_results if r.success and not r.deduplicated)
    deduplicated = sum(1 for r in all_results if r.deduplicated)
    failed = sum(1 for r in all_results if not r.success)

    logger.info(
        "Batch creation complete: %d successful, %d deduplicated, %d failed",
        successful,
        deduplicated,
        failed,
    )

    return BatchCreateResult(
        results=all_results,
        total=len(episodes),
        successful=successful,
        deduplicated=deduplicated,
        failed=failed,
        batches_used=len(batches),
    )


class EpisodeCreator:
    """
    Single entry point for all memory episode creation.

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
        self._repo = get_memory_repository()
        self._embedder = get_embedder()

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
        context_kind: str | None = None,
        applicability: dict[str, object] | None = None,
        tags: list[str] | None = None,
        summary: str | None = None,
        metadata: dict[str, object] | None = None,
        sensitivity_tier: str = "normal",
        changed_by: str | None = None,
        change_reason: str | None = None,
        bypass_compactness: bool = False,
    ) -> CreateResult:
        """Create a new memory episode in PostgreSQL.

        This is the ONLY method that should insert memories via the repository.
        """
        config = config or LEARNING
        reference_time = reference_time or datetime.now(UTC)

        return await create_episode_internal(
            repo=self._repo,
            embedder=self._embedder,
            group_id=self._group_id,
            content=content,
            name=name,
            config=config,
            source_description=source_description,
            reference_time=reference_time,
            injection_tier=injection_tier,
            context_kind=context_kind,
            applicability=applicability,
            tags=tags,
            summary=summary,
            metadata=metadata,
            sensitivity_tier=sensitivity_tier,
            changed_by=changed_by,
            change_reason=change_reason,
            bypass_compactness=bypass_compactness,
        )

    async def batch_create(
        self,
        episodes: list[BatchEpisodeRequest],
        *,
        max_tokens: int | None = None,
        concurrency: int | None = None,
    ) -> BatchCreateResult:
        """Create multiple episodes with token-aware batch packing."""
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
