"""Core episode creation logic."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from graphiti_core.nodes import EpisodeType as GraphitiEpisodeType

from .budget import count_tokens
from .dedup import find_exact_duplicate
from .episode_creator_models import CreateResult
from .episode_helpers import (
    build_simple_source_description,
    derive_injection_tier,
    set_token_count,
)
from .episode_validation import EpisodeValidator
from .graphiti_client import (
    GRAPHITI_LLM_MODEL,
    init_episode_usage_properties,
    set_episode_injection_tier,
)
from .ingestion_config import IngestionConfig

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


async def _add_episode_to_graphiti(
    graphiti: Any,
    group_id: str,
    content: str,
    name: str,
    source_description: str,
    reference_time: datetime,
) -> Any:
    """Call graphiti.add_episode and return the result."""
    return await graphiti.add_episode(
        name=name,
        episode_body=content,
        source=GraphitiEpisodeType.text,
        source_description=source_description,
        reference_time=reference_time,
        group_id=group_id,
    )


async def _apply_episode_metadata(
    graphiti: Any,
    episode_uuid: str,
    content: str,
    config: IngestionConfig,
    injection_tier: str | None,
    summary: str | None,
) -> None:
    """Apply post-creation metadata: tier, summary, usage tracking, token count."""
    tier = injection_tier or derive_injection_tier(config)
    if tier:
        await set_episode_injection_tier(episode_uuid, tier)

    if summary:
        from app.services.memory.graphiti_client import set_episode_summary

        await set_episode_summary(episode_uuid, summary)

    await init_episode_usage_properties(episode_uuid)

    token_count_value = count_tokens(content)
    await set_token_count(graphiti, episode_uuid, token_count_value)


async def _create_and_finalize(
    graphiti: Any,
    group_id: str,
    content: str,
    name: str,
    source_description: str,
    reference_time: datetime,
    config: IngestionConfig,
    injection_tier: str | None,
    summary: str | None,
) -> CreateResult:
    """Create episode via Graphiti and apply post-creation metadata."""
    # THIS IS THE ONLY PLACE THAT CALLS graphiti.add_episode
    try:
        result = await _add_episode_to_graphiti(
            graphiti, group_id, content, name, source_description, reference_time
        )
        episode_uuid = result.episode.uuid
        logger.info(
            "Created episode %s: %d entities, %d edges",
            episode_uuid,
            len(result.nodes),
            len(result.edges),
        )
        await _apply_episode_metadata(
            graphiti, episode_uuid, content, config, injection_tier, summary
        )
        return CreateResult(success=True, uuid=episode_uuid)
    except Exception as e:
        error_msg = str(e).lower()
        if "rate limit" in error_msg or "429" in error_msg or "resource exhausted" in error_msg:
            detail = (
                "Gemini API rate limit hit during Graphiti entity extraction "
                f"(model: {GRAPHITI_LLM_MODEL}). Wait a few minutes and retry."
            )
            logger.warning("Gemini rate limit during add_episode: %s", e)
            return CreateResult(success=False, validation_error=detail)
        logger.error("Failed to create episode: %s", e)
        return CreateResult(success=False, validation_error=f"Graphiti error: {e}")


async def create_episode_internal(
    graphiti: Any,
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
        graphiti: Graphiti client instance
        group_id: The group ID for the episode
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
        graphiti, group_id, content, name,
        source_description, reference_time,
        config, injection_tier, summary,
    )
