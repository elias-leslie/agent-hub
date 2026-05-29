"""
Query functions for finding tier optimization candidates.

Implements the core candidate discovery logic for tier optimization:
- Find episodes eligible for demotion (low utility, zombies, harmful ratings)
- Find episodes eligible for promotion (high utility, helpful ratings)
"""

from __future__ import annotations

import logging
from typing import Any

from .repository import get_memory_repository

logger = logging.getLogger(__name__)


def calculate_ghost_ratio(loaded: int, referenced: int) -> float:
    """Calculate ghost ratio (loaded / (referenced + 1))."""
    return loaded / (referenced + 1)


async def find_demotion_candidates(
    min_loads: int,
    grace_period_hours: int,
    min_age_days: int,
    harmful_threshold: int,
    ghost_ratio_threshold: float,
) -> list[dict[str, Any]]:
    """
    Find episodes eligible for demotion based on low lifecycle score or zombie status.

    Criteria:
    1. Low score: lifecycle_score < per-tier demotion threshold, loaded >= min_loads, age >= min_age_days
    2. Zombie: ghost_ratio > ghost_ratio_threshold (high loads, no references), neutral rating
    3. Harmful: harmful_count >= harmful_threshold

    Exclusions:
    - Pinned episodes (pinned=true) are never demoted
    - Episodes < grace_period_hours old

    Returns:
        List of demotion candidates with reason.
    """
    repo = get_memory_repository()

    try:
        raw_candidates = await repo.find_demotion_candidates(
            min_loads=min_loads,
            grace_period_hours=grace_period_hours,
            min_age_days=min_age_days,
            harmful_threshold=harmful_threshold,
            ghost_ratio_threshold=ghost_ratio_threshold,
        )

        # Normalize the candidate dicts to match the expected format
        candidates = []
        for c in raw_candidates:
            loaded = c.get("loaded_count", 0)
            referenced = c.get("referenced_count", 0)
            ghost = calculate_ghost_ratio(loaded, referenced)

            candidates.append({
                "uuid": c["uuid"],
                "name": c.get("name"),
                "current_tier": c.get("injection_tier", "reference"),
                "loaded_count": loaded,
                "referenced_count": referenced,
                "harmful_count": c.get("harmful_count", 0),
                "utility_score": c.get("utility_score", 0.0),
                "ghost_ratio": ghost,
                "lifecycle_score": c.get("lifecycle_score"),
                "age_hours": 0,  # Not needed for tier operations
                "reason": c.get("reason", "unknown"),
            })

        return candidates

    except Exception as e:
        logger.error("Failed to find demotion candidates: %s", e)
        return []


async def find_promotion_candidates(
    min_refs: int,
    min_age_days: int,
    helpful_threshold: int,
) -> list[dict[str, Any]]:
    """
    Find episodes eligible for promotion based on high lifecycle score.

    Criteria:
    - lifecycle_score >= per-tier promotion threshold, referenced >= min_refs, age >= min_age_days
    - OR helpful_count >= helpful_threshold

    Returns:
        List of promotion candidates with reason.
    """
    repo = get_memory_repository()

    try:
        raw_candidates = await repo.find_promotion_candidates(
            min_refs=min_refs,
            min_age_days=min_age_days,
            helpful_threshold=helpful_threshold,
        )

        # Normalize the candidate dicts to match the expected format
        candidates = []
        for c in raw_candidates:
            loaded = c.get("loaded_count", 0)
            referenced = c.get("referenced_count", 0)

            candidates.append({
                "uuid": c["uuid"],
                "name": c.get("name"),
                "current_tier": c.get("injection_tier", "reference"),
                "loaded_count": loaded,
                "referenced_count": referenced,
                "helpful_count": c.get("helpful_count", 0),
                "utility_score": c.get("utility_score", 0.0),
                "ghost_ratio": calculate_ghost_ratio(loaded, referenced),
                "lifecycle_score": c.get("lifecycle_score"),
                "age_hours": 0,  # Not needed for tier operations
                "reason": c.get("reason", "unknown"),
            })

        return candidates

    except Exception as e:
        logger.error("Failed to find promotion candidates: %s", e)
        return []
