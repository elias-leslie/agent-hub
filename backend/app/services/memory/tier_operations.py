"""
Core tier transition operations.

Implements tier promotion, demotion, and navigation logic.
"""

from __future__ import annotations

import logging

from .graphiti_client import get_graphiti

logger = logging.getLogger(__name__)

TIER_HIERARCHY = ["mandate", "guardrail", "reference"]


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

    Also sets vector_indexed=false for demoted episodes (ACE vector hygiene).

    Args:
        episode_uuid: Episode UUID
        new_tier: Target tier
        reason: Reason for demotion (for audit log)

    Returns:
        True if successful, False otherwise.
    """
    graphiti = get_graphiti()

    query = """
    MATCH (e:Episodic {uuid: $uuid})
    SET e.injection_tier = $new_tier,
        e.vector_indexed = false,
        e.demoted_at = datetime(),
        e.demotion_reason = $reason
    RETURN e.uuid AS uuid, e.injection_tier AS tier
    """

    try:
        records, _, _ = await graphiti.driver.execute_query(
            query,
            uuid=episode_uuid,
            new_tier=new_tier,
            reason=reason,
        )
        if records:
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
        new_tier: Target tier
        reason: Reason for promotion (for audit log)

    Returns:
        True if successful, False otherwise.
    """
    graphiti = get_graphiti()

    query = """
    MATCH (e:Episodic {uuid: $uuid})
    SET e.injection_tier = $new_tier,
        e.promoted_at = datetime(),
        e.promotion_reason = $reason
    RETURN e.uuid AS uuid, e.injection_tier AS tier
    """

    try:
        records, _, _ = await graphiti.driver.execute_query(
            query,
            uuid=episode_uuid,
            new_tier=new_tier,
            reason=reason,
        )
        if records:
            logger.info("Promoted episode %s to %s: %s", episode_uuid[:8], new_tier, reason)
            return True
        return False
    except Exception as e:
        logger.error("Failed to promote episode %s: %s", episode_uuid[:8], e)
        return False


async def log_tier_change(
    episode_uuid: str,
    old_tier: str,
    new_tier: str,
    reason: str,
    change_type: str,
) -> None:
    """
    Log a tier change to the audit table (PostgreSQL).

    Args:
        episode_uuid: Episode UUID
        old_tier: Previous tier
        new_tier: New tier
        reason: Reason for change
        change_type: 'demotion', 'promotion', or 'correction'
    """
    try:
        from sqlalchemy import text

        from app.db import _get_session_factory

        factory = _get_session_factory()
        async with factory() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO tier_change_log (episode_uuid, old_tier, new_tier, reason, change_type, created_at)
                    VALUES (:episode_uuid, :old_tier, :new_tier, :reason, :change_type, NOW())
                    """
                ),
                {
                    "episode_uuid": episode_uuid,
                    "old_tier": old_tier,
                    "new_tier": new_tier,
                    "reason": reason,
                    "change_type": change_type,
                },
            )
            await session.commit()
    except Exception as e:
        logger.error("Failed to log tier change: %s", e)
