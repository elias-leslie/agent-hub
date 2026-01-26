"""
Tier Optimizer for autonomous memory tier management.

Implements ACE-aligned optimization:
- Promotes high-utility episodes to higher tiers
- Demotes low-utility episodes to lower tiers
- Detects zombies (high load, zero reference) for cleanup
- Respects grace period for new episodes
- Logs all tier changes for audit trail

Thresholds (from Decision d5):
- Demote: utility_score < 0.15, loaded >= 50, age >= 7 days
- Demote zombie: ghost_ratio > 10, neutral avg rating
- Promote: utility_score > 0.70, referenced >= 20, age >= 7 days
- Grace period: 48 hours (no demotion for new episodes)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .graphiti_client import get_graphiti

logger = logging.getLogger(__name__)

DEMOTION_THRESHOLD = 0.15
PROMOTION_THRESHOLD = 0.70
MIN_LOADS_FOR_DEMOTION = 50
MIN_REFS_FOR_PROMOTION = 20
MIN_AGE_DAYS = 7
GRACE_PERIOD_HOURS = 48
GHOST_RATIO_THRESHOLD = 10

TIER_HIERARCHY = ["mandate", "guardrail", "reference"]


@dataclass
class TierCandidate:
    """Candidate for tier optimization."""

    uuid: str
    name: str
    current_tier: str
    loaded_count: int
    referenced_count: int
    utility_score: float
    ghost_ratio: float
    age_hours: float
    reason: str


def calculate_utility_score(loaded: int, referenced: int) -> float:
    """Calculate utility score (referenced / loaded)."""
    if loaded <= 0:
        return 0.5
    return min(1.0, referenced / loaded)


def calculate_ghost_ratio(loaded: int, referenced: int) -> float:
    """Calculate ghost ratio (loaded / (referenced + 1))."""
    return loaded / (referenced + 1)


async def find_demotion_candidates(
    grace_period_hours: int = GRACE_PERIOD_HOURS,
) -> list[dict[str, Any]]:
    """
    Find episodes eligible for demotion based on low utility or zombie status.

    Criteria:
    1. Low utility: utility_score < 0.15, loaded >= 50, age >= 7 days
    2. Zombie: ghost_ratio > 10 (high loads, no references), neutral rating

    Grace period: Episodes < 48h old are exempt from demotion.

    Returns:
        List of demotion candidates with reason.
    """
    graphiti = get_graphiti()

    query = """
    MATCH (e:Episodic)
    WHERE e.injection_tier IN ['mandate', 'guardrail']
      AND e.loaded_count >= $min_loads
      AND duration.between(e.created_at, datetime()).days >= $grace_days
      AND duration.between(e.created_at, datetime()).days >= $min_days
    RETURN
        e.uuid AS uuid,
        e.name AS name,
        e.injection_tier AS tier,
        e.loaded_count AS loaded,
        coalesce(e.referenced_count, 0) AS referenced,
        e.created_at AS created_at
    """

    candidates = []
    try:
        records, _, _ = await graphiti.driver.execute_query(
            query,
            min_loads=MIN_LOADS_FOR_DEMOTION,
            grace_days=grace_period_hours // 24,
            min_days=MIN_AGE_DAYS,
        )

        for record in records:
            loaded = record["loaded"]
            referenced = record["referenced"]
            utility = calculate_utility_score(loaded, referenced)
            ghost = calculate_ghost_ratio(loaded, referenced)

            created_at = record["created_at"]
            if hasattr(created_at, "to_native"):
                created_at = created_at.to_native()
            age_hours = (datetime.now(UTC) - created_at.replace(tzinfo=UTC)).total_seconds() / 3600

            reason = None
            if utility < DEMOTION_THRESHOLD:
                reason = f"low_utility:{utility:.2f}"
            elif ghost > GHOST_RATIO_THRESHOLD:
                reason = f"zombie:ghost_ratio={ghost:.1f}"

            if reason:
                candidates.append({
                    "uuid": record["uuid"],
                    "name": record["name"],
                    "current_tier": record["tier"],
                    "loaded_count": loaded,
                    "referenced_count": referenced,
                    "utility_score": utility,
                    "ghost_ratio": ghost,
                    "age_hours": age_hours,
                    "reason": reason,
                })

    except Exception as e:
        logger.error("Failed to find demotion candidates: %s", e)

    return candidates


async def find_promotion_candidates() -> list[dict[str, Any]]:
    """
    Find episodes eligible for promotion based on high utility.

    Criteria: utility_score > 0.70, referenced >= 20, age >= 7 days

    Returns:
        List of promotion candidates with reason.
    """
    graphiti = get_graphiti()

    query = """
    MATCH (e:Episodic)
    WHERE e.injection_tier IN ['guardrail', 'reference']
      AND coalesce(e.referenced_count, 0) >= $min_refs
      AND duration.between(e.created_at, datetime()).days >= $min_days
    RETURN
        e.uuid AS uuid,
        e.name AS name,
        e.injection_tier AS tier,
        coalesce(e.loaded_count, 0) AS loaded,
        e.referenced_count AS referenced,
        e.created_at AS created_at
    """

    candidates = []
    try:
        records, _, _ = await graphiti.driver.execute_query(
            query,
            min_refs=MIN_REFS_FOR_PROMOTION,
            min_days=MIN_AGE_DAYS,
        )

        for record in records:
            loaded = record["loaded"]
            referenced = record["referenced"]
            utility = calculate_utility_score(loaded, referenced)

            if utility > PROMOTION_THRESHOLD:
                created_at = record["created_at"]
                if hasattr(created_at, "to_native"):
                    created_at = created_at.to_native()
                age_hours = (datetime.now(UTC) - created_at.replace(tzinfo=UTC)).total_seconds() / 3600

                candidates.append({
                    "uuid": record["uuid"],
                    "name": record["name"],
                    "current_tier": record["tier"],
                    "loaded_count": loaded,
                    "referenced_count": referenced,
                    "utility_score": utility,
                    "ghost_ratio": calculate_ghost_ratio(loaded, referenced),
                    "age_hours": age_hours,
                    "reason": f"high_utility:{utility:.2f}",
                })

    except Exception as e:
        logger.error("Failed to find promotion candidates: %s", e)

    return candidates


async def create_correction_node(
    original_uuid: str,
    correction_content: str,
    reason: str,
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

    Returns:
        UUID of the correction node, or None on failure
    """
    import uuid

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
            await log_tier_change(
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
) -> bool:
    """
    Handle an episode that has harmful rating majority.

    If correction_content is provided, creates a correction node.
    Otherwise, just sets vector_indexed=false to remove from search.

    Args:
        episode_uuid: UUID of the harmful episode
        correction_content: Optional corrected content to replace harmful one

    Returns:
        True if handled successfully, False otherwise
    """
    if correction_content:
        correction_uuid = await create_correction_node(
            episode_uuid,
            correction_content,
            "harmful_rating_majority",
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
        change_type: 'demotion' or 'promotion'
    """
    try:
        import asyncpg

        from app.config import settings

        conn = await asyncpg.connect(settings.agent_hub_db_url)
        try:
            await conn.execute(
                """
                INSERT INTO tier_change_log (episode_uuid, old_tier, new_tier, reason, change_type, created_at)
                VALUES ($1, $2, $3, $4, $5, NOW())
                """,
                episode_uuid,
                old_tier,
                new_tier,
                reason,
                change_type,
            )
        finally:
            await conn.close()
    except Exception as e:
        logger.error("Failed to log tier change: %s", e)


async def optimize_tiers() -> dict[str, Any]:
    """
    Run the tier optimization cycle.

    1. Find demotion candidates (low utility, zombies)
    2. Find promotion candidates (high utility)
    3. Apply tier changes
    4. Log all changes to audit table

    Returns:
        Summary of optimization results.
    """
    results = {
        "demotions": 0,
        "promotions": 0,
        "errors": 0,
        "details": [],
    }

    demotion_candidates = await find_demotion_candidates()
    for candidate in demotion_candidates:
        new_tier = get_next_tier_down(candidate["current_tier"])
        if new_tier:
            success = await demote_episode(candidate["uuid"], new_tier, candidate["reason"])
            if success:
                await log_tier_change(
                    candidate["uuid"],
                    candidate["current_tier"],
                    new_tier,
                    candidate["reason"],
                    "demotion",
                )
                results["demotions"] += 1
                results["details"].append({
                    "uuid": candidate["uuid"][:8],
                    "action": "demote",
                    "from": candidate["current_tier"],
                    "to": new_tier,
                    "reason": candidate["reason"],
                })
            else:
                results["errors"] += 1

    promotion_candidates = await find_promotion_candidates()
    for candidate in promotion_candidates:
        new_tier = get_next_tier_up(candidate["current_tier"])
        if new_tier:
            success = await promote_episode(candidate["uuid"], new_tier, candidate["reason"])
            if success:
                await log_tier_change(
                    candidate["uuid"],
                    candidate["current_tier"],
                    new_tier,
                    candidate["reason"],
                    "promotion",
                )
                results["promotions"] += 1
                results["details"].append({
                    "uuid": candidate["uuid"][:8],
                    "action": "promote",
                    "from": candidate["current_tier"],
                    "to": new_tier,
                    "reason": candidate["reason"],
                })
            else:
                results["errors"] += 1

    logger.info(
        "Tier optimization complete: %d demotions, %d promotions, %d errors",
        results["demotions"],
        results["promotions"],
        results["errors"],
    )

    return results
