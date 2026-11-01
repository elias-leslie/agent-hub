"""
Core tier transition operations.

Implements tier promotion, demotion, and navigation logic.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from .repository import get_memory_repository

logger = logging.getLogger(__name__)

TIER_HIERARCHY = ["mandate", "guardrail", "reference", "archive"]
# Tier moves are memory revisions (tier is a column there) written by this actor, with the reason.
TIER_ACTOR = "system:tier-optimizer"


def get_next_tier_down(current_tier: str) -> str | None:
    """Get the next lower tier for demotion."""
    try:
        idx = TIER_HIERARCHY.index(current_tier)
        if idx < len(TIER_HIERARCHY) - 1:
            return TIER_HIERARCHY[idx + 1]
    except ValueError:
        pass
    return None


def get_next_tier_up(current_tier: str) -> str | None:
    """Get the next higher tier for promotion."""
    try:
        idx = TIER_HIERARCHY.index(current_tier)
        if idx > 0:
            return TIER_HIERARCHY[idx - 1]
    except ValueError:
        pass
    return None


async def demote_episode(
    episode_uuid: str,
    new_tier: str,
    reason: str,
) -> bool:
    """
    Demote an episode to a lower tier.

    Args:
        episode_uuid: Episode UUID
        new_tier: Target tier (string name: 'guardrail', 'reference')
        reason: Reason for demotion (kept on the memory revision)

    Returns:
        True if successful, False otherwise.
    """
    repo = get_memory_repository()

    try:
        success = await repo.update(
            episode_uuid,
            injection_tier=new_tier,
            demoted_at=datetime.now(UTC),
            demotion_reason=reason,
            changed_by=TIER_ACTOR,
            change_reason=reason,
        )
        if success:
            logger.info("Demoted episode %s to %s: %s", episode_uuid[:8], new_tier, reason)
            return True
        return False
    except Exception as e:
        logger.error("Failed to demote episode %s: %s", episode_uuid[:8], e)
        return False


async def promote_episode(
    episode_uuid: str,
    new_tier: str,
    reason: str,
) -> bool:
    """
    Promote an episode to a higher tier.

    Args:
        episode_uuid: Episode UUID
        new_tier: Target tier (string name: 'mandate', 'guardrail')
        reason: Reason for promotion (kept on the memory revision)

    Returns:
        True if successful, False otherwise.
    """
    repo = get_memory_repository()

    try:
        success = await repo.update(
            episode_uuid,
            injection_tier=new_tier,
            changed_by=TIER_ACTOR,
            change_reason=reason,
        )
        if success:
            logger.info("Promoted episode %s to %s: %s", episode_uuid[:8], new_tier, reason)
            return True
        return False
    except Exception as e:
        logger.error("Failed to promote episode %s: %s", episode_uuid[:8], e)
        return False
