"""Core episode creation logic.

Inserts memories into PostgreSQL via MemoryRepository with embeddings
from the standalone EmbedderService. Replaces the former Graphiti/Neo4j
add_episode path (which performed ~20 LLM API calls for entity extraction)
with a single embed() call + one SQL INSERT.
"""

from __future__ import annotations

import logging
from datetime import datetime

from .budget import count_tokens
from .dedup import find_exact_duplicate
from .embedder import EMBEDDING_MODEL, EmbedderService
from .episode_creator_models import CreateResult
from .episode_helpers import (
    build_simple_source_description,
    derive_injection_tier,
)
from .episode_validation import EpisodeValidator
from .ingestion_config import IngestionConfig
from .repository import TIER_MAP, MemoryRepository

logger = logging.getLogger(__name__)


async def _validate_content(content: str, config: IngestionConfig) -> CreateResult | None:
    """Return a failure CreateResult if validation fails, else None."""
    if not config.validate:
        return None
    validation_error = EpisodeValidator.validate_content_simple(content)
    if validation_error:
        return CreateResult(success=False, validation_error=validation_error)
    return None


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


async def _embed_content(
    embedder: EmbedderService,
    content: str,
) -> list[float]:
    """Generate embedding vector for content via the standalone embedder."""
    return await embedder.embed(content)


async def _insert_memory(
    repo: MemoryRepository,
    *,
    content: str,
    name: str,
    group_id: str,
    source_description: str,
    reference_time: datetime,
    embedding: list[float],
    tier: int,
    summary: str | None,
    token_count: int,
) -> str:
    """Insert a memory row via MemoryRepository.create() and return its UUID."""
    memory = await repo.create(
        content=content,
        name=name,
        memory_type="episode",
        group_id=group_id,
        source_description=source_description,
        embedding=embedding,
        tier=tier,
        summary=summary,
        token_count=token_count,
        valid_at=reference_time,
    )
    return str(memory.id)


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
    summary: str | None,
) -> CreateResult:
    """Embed content, insert into PostgreSQL, and return result."""
    try:
        # 1. Compute embedding (single API call)
        embedding = await _embed_content(embedder, content)

        # 2. Resolve tier
        tier_name = injection_tier or derive_injection_tier(config)
        tier_num = TIER_MAP.get(tier_name, 3)

        # 3. Count tokens
        token_count_value = count_tokens(content)

        # 4. Insert into PostgreSQL (single SQL INSERT)
        episode_uuid = await _insert_memory(
            repo,
            content=content,
            name=name,
            group_id=group_id,
            source_description=source_description,
            reference_time=reference_time,
            embedding=embedding,
            tier=tier_num,
            summary=summary,
            token_count=token_count_value,
        )

        logger.info(
            "Created memory %s (tier=%s, tokens=%d)",
            episode_uuid,
            tier_name,
            token_count_value,
        )
        return CreateResult(success=True, uuid=episode_uuid)

    except Exception as e:
        error_msg = str(e).lower()
        if "rate limit" in error_msg or "429" in error_msg or "resource exhausted" in error_msg:
            from app.adapters.gemini_errors import extract_gemini_quota_details

            quota = extract_gemini_quota_details(e)
            quota_summary = ""
            if quota.get("quota_metric"):
                quota_summary = (
                    f" [metric={quota.get('quota_metric')}"
                    f" limit={quota.get('quota_limit', '?')}"
                    f" consumer={quota.get('consumer', '?')}]"
                )
            detail = (
                "Gemini API rate limit hit during embedding "
                f"(model: {EMBEDDING_MODEL}).{quota_summary} Wait a few minutes and retry."
            )
            logger.warning(
                "Gemini rate limit during embed%s: %s", quota_summary, e,
            )
            return CreateResult(success=False, validation_error=detail)
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
    summary: str | None,
) -> CreateResult:
    """Internal implementation of episode creation.

    Args:
        repo: MemoryRepository instance for PostgreSQL access
        embedder: EmbedderService instance for generating embeddings
        group_id: The group ID for the memory
        content: The episode content/body
        name: Episode name (slug-like identifier)
        config: Ingestion configuration
        source_description: Human-readable source description
        reference_time: When the episode occurred
        injection_tier: Explicit tier override (mandate/guardrail/reference)
        summary: Optional summary for the episode

    Returns:
        CreateResult with success status, UUID if created, or error info
    """
    if (result := await _validate_content(content, config)) is not None:
        return result

    if (result := await _check_duplicate(content, config)) is not None:
        return result

    if not source_description:
        source_description = build_simple_source_description(config)

    return await _create_and_finalize(
        repo, embedder, group_id, content, name,
        source_description, reference_time,
        config, injection_tier, summary,
    )
