"""Core episode creation logic."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

from graphiti_core.nodes import EpisodeType as GraphitiEpisodeType

from .budget import count_tokens
from .dedup import find_exact_duplicate
from .episode_creator_helpers import (
    build_source_description,
    derive_injection_tier,
    set_token_count,
)
from .episode_creator_models import CreateResult
from .episode_creator_validation import validate_content
from .graphiti_client import (
    init_episode_usage_properties,
    set_episode_injection_tier,
)
from .ingestion_config import IngestionConfig

logger = logging.getLogger(__name__)

# Summary length constraints (matching episode_validation.py)
_SUMMARY_MIN = 10
_SUMMARY_MAX = 50


def generate_summary_from_content(content: str) -> str:
    """Generate a short summary from episode content.

    Extracts a meaningful prefix: uses the bold header topic if present
    (e.g. '**Service Scripts**: ...' -> 'Service Scripts'), otherwise
    takes the first ~40 chars of content and truncates at a word boundary.

    Returns:
        A summary string between 10 and 50 chars.
    """
    # Try to extract bold header topic: **Topic**: ...
    header_match = re.match(r"^\*\*([^*]+)\*\*", content)
    if header_match:
        topic = header_match.group(1).strip()
        if _SUMMARY_MIN <= len(topic) <= _SUMMARY_MAX:
            return topic
        if len(topic) > _SUMMARY_MAX:
            return topic[:_SUMMARY_MAX - 3].rsplit(" ", 1)[0] + "..."

    # Strip markdown/formatting prefixes
    text = re.sub(r"^\[.*?\]\s*", "", content).strip()
    text = re.sub(r"^\*\*.*?\*\*:?\s*", "", text).strip()

    if len(text) <= _SUMMARY_MAX:
        return text if len(text) >= _SUMMARY_MIN else text.ljust(_SUMMARY_MIN)

    # Truncate at word boundary
    truncated = text[:_SUMMARY_MAX - 3]
    last_space = truncated.rfind(" ")
    if last_space > _SUMMARY_MIN:
        truncated = truncated[:last_space]
    return truncated.rstrip(".,;:!? ") + "..."


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
    """
    Internal implementation of episode creation.

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
    # Step 1: Validate content if configured
    if config.validate:
        validation_error = validate_content(content)
        if validation_error:
            return CreateResult(
                success=False,
                validation_error=validation_error,
            )

    # Step 2: Check for duplicates if configured
    if config.deduplicate:
        duplicate = await find_exact_duplicate(content, config.dedup_window_minutes)
        if duplicate:
            logger.debug("Skipping duplicate content: %s", content[:50])
            return CreateResult(
                success=True,
                uuid=duplicate,
                deduplicated=True,
            )

    # Step 3: Build source description with metadata
    if not source_description:
        source_description = build_source_description(config)

    # Step 4: Create the episode via Graphiti
    # THIS IS THE ONLY PLACE THAT CALLS graphiti.add_episode
    try:
        result = await graphiti.add_episode(
            name=name,
            episode_body=content,
            source=GraphitiEpisodeType.text,
            source_description=source_description,
            reference_time=reference_time,
            group_id=group_id,
        )

        episode_uuid = result.episode.uuid
        logger.info(
            "Created episode %s: %d entities, %d edges",
            episode_uuid,
            len(result.nodes),
            len(result.edges),
        )

        # Step 5: Set injection_tier on the Neo4j node
        tier = injection_tier or derive_injection_tier(config)
        if tier:
            await set_episode_injection_tier(episode_uuid, tier)

        # Step 5b: Set summary (auto-generate from content if not provided)
        from app.services.memory.graphiti_client import set_episode_summary

        effective_summary = summary or generate_summary_from_content(content)
        await set_episode_summary(episode_uuid, effective_summary)

        # Step 6: Initialize usage tracking properties (loaded_count=0, referenced_count=0)
        await init_episode_usage_properties(episode_uuid)

        # Step 7: Set token_count for utility-per-token scoring
        token_count_value = count_tokens(content)
        await set_token_count(graphiti, episode_uuid, token_count_value)

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
