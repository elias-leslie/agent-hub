"""
Query functions for finding tier optimization candidates.

Implements the core candidate discovery logic for tier optimization:
- Find episodes eligible for demotion (low utility, zombies, harmful ratings)
- Find episodes eligible for promotion (high utility, helpful ratings)
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from .graphiti_client import get_graphiti
from .scoring import calculate_usage_effectiveness

logger = logging.getLogger(__name__)


def calculate_ghost_ratio(loaded: int, referenced: int) -> float:
    """Calculate ghost ratio (loaded / (referenced + 1))."""
    return loaded / (referenced + 1)


async def find_demotion_candidates(
    min_loads: int,
    grace_period_hours: int,
    min_age_days: int,
    harmful_threshold: int,
    demotion_threshold: float,
    ghost_ratio_threshold: float,
) -> list[dict[str, Any]]:
    """
    Find episodes eligible for demotion based on low utility or zombie status.

    Criteria:
    1. Low utility: utility_score < demotion_threshold, loaded >= min_loads, age >= min_age_days
    2. Zombie: ghost_ratio > ghost_ratio_threshold (high loads, no references), neutral rating
    3. Harmful: harmful_count >= harmful_threshold

    Exclusions:
    - Pinned episodes (pinned=true) are never demoted
    - Episodes < grace_period_hours old

    Returns:
        List of demotion candidates with reason.
    """
    graphiti = get_graphiti()

    query = """
    MATCH (e:Episodic)
    WHERE e.injection_tier IN ['mandate', 'guardrail']
      AND COALESCE(e.pinned, false) = false
      AND (
          (e.loaded_count >= $min_loads
           AND duration.between(e.created_at, datetime()).days >= $grace_days
           AND duration.between(e.created_at, datetime()).days >= $min_days)
          OR coalesce(e.harmful_count, 0) >= $harmful_threshold
      )
    RETURN
        e.uuid AS uuid,
        e.name AS name,
        e.injection_tier AS tier,
        e.loaded_count AS loaded,
        coalesce(e.referenced_count, 0) AS referenced,
        coalesce(e.harmful_count, 0) AS harmful,
        coalesce(e.helpful_count, 0) AS helpful,
        e.created_at AS created_at
    """

    candidates = []
    try:
        records, _, _ = await graphiti.driver.execute_query(
            query,
            min_loads=min_loads,
            grace_days=grace_period_hours // 24,
            min_days=min_age_days,
            harmful_threshold=harmful_threshold,
        )

        for record in records:
            loaded = record["loaded"]
            referenced = record["referenced"]
            harmful = record["harmful"]
            utility = calculate_usage_effectiveness(loaded, referenced)
            ghost = calculate_ghost_ratio(loaded, referenced)

            created_at = record["created_at"]
            if hasattr(created_at, "to_native"):
                created_at = created_at.to_native()
            age_hours = (datetime.now(UTC) - created_at.replace(tzinfo=UTC)).total_seconds() / 3600

            reason = None
            # ACE-aligned: harmful ratings take priority
            if harmful >= harmful_threshold:
                reason = f"harmful_ratings:{harmful}"
            elif utility < demotion_threshold:
                reason = f"low_utility:{utility:.2f}"
            elif ghost > ghost_ratio_threshold:
                reason = f"zombie:ghost_ratio={ghost:.1f}"

            if reason:
                candidates.append(
                    {
                        "uuid": record["uuid"],
                        "name": record["name"],
                        "current_tier": record["tier"],
                        "loaded_count": loaded,
                        "referenced_count": referenced,
                        "harmful_count": harmful,
                        "utility_score": utility,
                        "ghost_ratio": ghost,
                        "age_hours": age_hours,
                        "reason": reason,
                    }
                )

    except Exception as e:
        logger.error("Failed to find demotion candidates: %s", e)

    return candidates


async def find_promotion_candidates(
    min_refs: int,
    min_age_days: int,
    helpful_threshold: int,
    promotion_threshold: float,
) -> list[dict[str, Any]]:
    """
    Find episodes eligible for promotion based on high utility.

    Criteria:
    - utility_score > promotion_threshold, referenced >= min_refs, age >= min_age_days
    - OR helpful_count >= helpful_threshold

    Returns:
        List of promotion candidates with reason.
    """
    graphiti = get_graphiti()

    query = """
    MATCH (e:Episodic)
    WHERE e.injection_tier IN ['guardrail', 'reference']
      AND (
          (coalesce(e.referenced_count, 0) >= $min_refs
           AND duration.between(e.created_at, datetime()).days >= $min_days)
          OR coalesce(e.helpful_count, 0) >= $helpful_threshold
      )
    RETURN
        e.uuid AS uuid,
        e.name AS name,
        e.injection_tier AS tier,
        coalesce(e.loaded_count, 0) AS loaded,
        coalesce(e.referenced_count, 0) AS referenced,
        coalesce(e.harmful_count, 0) AS harmful,
        coalesce(e.helpful_count, 0) AS helpful,
        e.created_at AS created_at
    """

    candidates = []
    try:
        records, _, _ = await graphiti.driver.execute_query(
            query,
            min_refs=min_refs,
            min_days=min_age_days,
            helpful_threshold=helpful_threshold,
        )

        for record in records:
            loaded = record["loaded"]
            referenced = record["referenced"]
            helpful = record["helpful"]
            utility = calculate_usage_effectiveness(loaded, referenced)

            # ACE-aligned: helpful ratings take priority, then high utility
            if helpful >= helpful_threshold or utility > promotion_threshold:
                created_at = record["created_at"]
                if hasattr(created_at, "to_native"):
                    created_at = created_at.to_native()
                age_hours = (
                    datetime.now(UTC) - created_at.replace(tzinfo=UTC)
                ).total_seconds() / 3600

                reason = (
                    f"helpful_ratings:{helpful}"
                    if helpful >= helpful_threshold
                    else f"high_utility:{utility:.2f}"
                )
                candidates.append(
                    {
                        "uuid": record["uuid"],
                        "name": record["name"],
                        "current_tier": record["tier"],
                        "loaded_count": loaded,
                        "referenced_count": referenced,
                        "helpful_count": helpful,
                        "utility_score": utility,
                        "ghost_ratio": calculate_ghost_ratio(loaded, referenced),
                        "age_hours": age_hours,
                        "reason": reason,
                    }
                )

    except Exception as e:
        logger.error("Failed to find promotion candidates: %s", e)

    return candidates
