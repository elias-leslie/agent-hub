"""Core episode creation logic.

Inserts memories into PostgreSQL via MemoryRepository with embeddings
from EmbedderService — one embed() call + one SQL INSERT.
"""

from __future__ import annotations

import logging
from datetime import datetime

from .budget import count_tokens
from .dedup import find_exact_duplicate
from .embedder import EmbedderService
from .episode_creator_helpers import (
    build_source_quality_metadata,
    handle_rate_limit_error,
    insert_memory,
    is_rate_limit_error,
    validate_content,
)
from .episode_creator_models import CreateResult
from .episode_helpers import (
    build_simple_source_description,
    derive_injection_tier,
)
from .ingestion_config import IngestionConfig
from .repository import TIER_MAP, MemoryRepository

logger = logging.getLogger(__name__)


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
) -> CreateResult:
    """Internal implementation of episode creation."""
    if (result := validate_content(content, config)) is not None:
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
