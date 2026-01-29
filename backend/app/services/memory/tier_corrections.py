"""
Correction handling for harmful episodes.

Implements the ACE-aligned correction workflow:
- Create correction nodes that replace harmful episodes
- Mark harmful episodes as not vector-indexed
- Log corrections for audit trail
"""

from __future__ import annotations

import logging
import uuid
from typing import Awaitable, Callable

from .graphiti_client import get_graphiti

logger = logging.getLogger(__name__)


async def create_correction_node(
    original_uuid: str,
    correction_content: str,
    reason: str,
    log_tier_change_fn: Callable[[str, str, str, str, str], Awaitable[None]],
) -> str | None:
    """
    Create a correction node that REPLACES a harmful episode.

    When an episode has a harmful rating majority, we:
    1. Create a new correction episode with the corrected information
    2. Link it to original via REPLACES relationship
    3. Set original's vector_indexed=false (remove from search)
    4. Log the correction in tier_change_log

    Args:
        original_uuid: UUID of the harmful episode to correct
        correction_content: The corrected content to replace the harmful one
        reason: Reason for creating the correction
        log_tier_change_fn: Function to log tier changes

    Returns:
        UUID of the correction node, or None on failure
    """
    graphiti = get_graphiti()
    correction_uuid = str(uuid.uuid4())

    query = """
    MATCH (original:Episodic {uuid: $original_uuid})
    CREATE (correction:Episodic {
        uuid: $correction_uuid,
        name: 'correction_' + original.name,
        content: $correction_content,
        group_id: original.group_id,
        injection_tier: original.injection_tier,
        loaded_count: 0,
        referenced_count: 0,
        vector_indexed: true,
        created_at: datetime(),
        is_correction: true,
        corrects_uuid: $original_uuid
    })
    CREATE (correction)-[:REPLACES]->(original)
    SET original.vector_indexed = false,
        original.has_correction = true,
        original.correction_uuid = $correction_uuid,
        original.correction_reason = $reason
    RETURN correction.uuid AS uuid
    """

    try:
        records, _, _ = await graphiti.driver.execute_query(
            query,
            original_uuid=original_uuid,
            correction_uuid=correction_uuid,
            correction_content=correction_content,
            reason=reason,
        )
        if records:
            logger.info(
                "Created correction %s for harmful episode %s: %s",
                correction_uuid[:8],
                original_uuid[:8],
                reason,
            )
            await log_tier_change_fn(
                original_uuid,
                "harmful",
                "corrected",
                f"correction_created:{correction_uuid[:8]}",
                "correction",
            )
            return correction_uuid
        return None
    except Exception as e:
        logger.error("Failed to create correction for %s: %s", original_uuid[:8], e)
        return None


async def handle_harmful_episode(
    episode_uuid: str,
    correction_content: str | None = None,
    log_tier_change_fn: Callable[[str, str, str, str, str], Awaitable[None]] | None = None,
) -> bool:
    """
    Handle an episode that has harmful rating majority.

    If correction_content is provided, creates a correction node.
    Otherwise, just sets vector_indexed=false to remove from search.

    Args:
        episode_uuid: UUID of the harmful episode
        correction_content: Optional corrected content to replace harmful one
        log_tier_change_fn: Function to log tier changes (required if correction_content provided)

    Returns:
        True if handled successfully, False otherwise
    """
    if correction_content:
        if not log_tier_change_fn:
            logger.error("log_tier_change_fn required for correction creation")
            return False
        correction_uuid = await create_correction_node(
            episode_uuid,
            correction_content,
            "harmful_rating_majority",
            log_tier_change_fn,
        )
        return correction_uuid is not None

    graphiti = get_graphiti()
    query = """
    MATCH (e:Episodic {uuid: $uuid})
    SET e.vector_indexed = false,
        e.marked_harmful = true,
        e.harmful_at = datetime()
    RETURN e.uuid AS uuid
    """

    try:
        records, _, _ = await graphiti.driver.execute_query(
            query,
            uuid=episode_uuid,
        )
        if records:
            logger.info("Marked episode %s as harmful (removed from search)", episode_uuid[:8])
            return True
        return False
    except Exception as e:
        logger.error("Failed to handle harmful episode %s: %s", episode_uuid[:8], e)
        return False
