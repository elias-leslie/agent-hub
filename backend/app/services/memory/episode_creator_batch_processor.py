"""Batch processing utilities for episode creation."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from .episode_creator_batching import (
    EMBEDDING_BATCH_CONCURRENCY,
    EMBEDDING_BATCH_MAX_TOKENS,
    pack_episodes_into_batches,
)
from .episode_creator_models import BatchCreateResult, BatchEpisodeRequest, CreateResult

if TYPE_CHECKING:
    from .episode_creator import EpisodeCreator

logger = logging.getLogger(__name__)


async def batch_create_episodes(
    creator: EpisodeCreator,
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
        creator: EpisodeCreator instance to use for creation
        episodes: List of BatchEpisodeRequest to create
        max_tokens: Max tokens per batch (default: EMBEDDING_BATCH_MAX_TOKENS)
        concurrency: Max concurrent batches (default: EMBEDDING_BATCH_CONCURRENCY)

    Returns:
        BatchCreateResult with individual results and summary statistics
    """
    if not episodes:
        return BatchCreateResult()

    max_tokens = max_tokens or EMBEDDING_BATCH_MAX_TOKENS
    concurrency = concurrency or EMBEDDING_BATCH_CONCURRENCY

    # Pack episodes into token-aware batches
    batches = pack_episodes_into_batches(episodes, max_tokens)

    logger.info(
        "Batch creating %d episodes in %d batches (max %d tokens/batch, %d concurrent)",
        len(episodes),
        len(batches),
        max_tokens,
        concurrency,
    )

    # Process batches with controlled concurrency
    all_results = await _process_batches(creator, batches, concurrency)

    # Calculate statistics
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


async def _process_batches(
    creator: EpisodeCreator,
    batches: list[list[BatchEpisodeRequest]],
    concurrency: int,
) -> list[CreateResult]:
    """Process batches with controlled concurrency."""
    semaphore = asyncio.Semaphore(concurrency)
    all_results: list[CreateResult] = []

    async def process_batch(batch: list[BatchEpisodeRequest]) -> list[CreateResult]:
        """Process a single batch of episodes."""
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

    # Run all batches concurrently (limited by semaphore)
    batch_tasks = [process_batch(batch) for batch in batches]
    batch_results = await asyncio.gather(*batch_tasks)

    # Flatten results
    for batch_result in batch_results:
        all_results.extend(batch_result)

    return all_results
