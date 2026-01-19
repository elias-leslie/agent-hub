"""
Memory promotion service for reinforcement-based learning.

Implements the two-state system (per decision d2):
- provisional: 70-89 confidence, needs reinforcement
- canonical: 90+ confidence, trusted

Promotion happens when:
1. A new learning semantically matches an existing provisional learning
2. Manual promotion via API
"""

import logging

from pydantic import BaseModel, Field

from .graphiti_client import get_graphiti
from .learning_extractor import CANONICAL_THRESHOLD

logger = logging.getLogger(__name__)

# Similarity threshold for considering two learnings as "matching"
SIMILARITY_THRESHOLD = 0.8


class PromotionResult(BaseModel):
    """Result of a promotion operation."""

    success: bool
    promoted: bool = False
    episode_uuid: str | None = None
    message: str
    previous_status: str | None = None
    new_status: str | None = None


class PromoteRequest(BaseModel):
    """Request to manually promote a learning."""

    episode_uuid: str = Field(..., description="UUID of the episode to promote")
    reason: str | None = Field(None, description="Reason for manual promotion")


class ReinforcementResult(BaseModel):
    """Result of checking for reinforcement."""

    found_match: bool = False
    promoted: bool = False
    matched_uuid: str | None = None
    new_confidence: float | None = None


async def check_and_promote_duplicate(
    content: str,
    confidence: float,
) -> ReinforcementResult:
    """
    Check if a new learning matches an existing provisional learning.

    If a semantic match is found with a provisional learning, promote it to canonical.

    Args:
        content: The new learning content
        confidence: Confidence of the new learning

    Returns:
        ReinforcementResult indicating if promotion occurred
    """
    graphiti = get_graphiti()
    result = ReinforcementResult()

    try:
        # Search for semantically similar existing learnings
        edges = await graphiti.search(
            query=content,
            group_ids=["global"],  # Per d4: shared global scope
            num_results=5,
        )

        if not edges:
            return result

        # Look for provisional matches
        for edge in edges:
            score = getattr(edge, "score", 0.0)
            if score < SIMILARITY_THRESHOLD:
                continue

            # Check if this is a provisional learning
            source_desc = getattr(edge, "source_description", "") or ""
            if "status:provisional" not in source_desc:
                continue

            # Found a matching provisional learning - promote it
            result.found_match = True
            result.matched_uuid = edge.uuid

            # Calculate new confidence (average of existing + new, capped at 100)
            existing_conf = _extract_confidence(source_desc)
            new_conf = min(100, (existing_conf + confidence) / 2 + 10)  # Boost on reinforcement
            result.new_confidence = new_conf

            if new_conf >= CANONICAL_THRESHOLD:
                # Promote to canonical
                new_source_desc = source_desc.replace(
                    "status:provisional", "status:canonical"
                ).replace(f"confidence:{existing_conf:.0f}", f"confidence:{new_conf:.0f}")

                await _update_edge_source_description(edge.uuid, new_source_desc)
                result.promoted = True

                logger.info(
                    "Promoted learning %s from provisional to canonical "
                    "(old_conf=%.0f, new_conf=%.0f)",
                    edge.uuid,
                    existing_conf,
                    new_conf,
                )
            else:
                # Just update confidence
                new_source_desc = source_desc.replace(
                    f"confidence:{existing_conf:.0f}", f"confidence:{new_conf:.0f}"
                )
                await _update_edge_source_description(edge.uuid, new_source_desc)

                logger.info(
                    "Reinforced provisional learning %s (old_conf=%.0f, new_conf=%.0f)",
                    edge.uuid,
                    existing_conf,
                    new_conf,
                )

            return result  # Only process first match

    except Exception as e:
        logger.error("Failed to check for duplicate learnings: %s", e)

    return result


async def promote_learning(request: PromoteRequest) -> PromotionResult:
    """
    Manually promote a learning to canonical status.

    Args:
        request: Promotion request with episode UUID

    Returns:
        PromotionResult indicating success
    """
    graphiti = get_graphiti()

    try:
        # Find the edge by UUID
        driver = graphiti.driver
        query = """
        MATCH (e:EntityEdge {uuid: $uuid})
        RETURN e.source_description AS source_desc, e.uuid AS uuid
        """
        records, _, _ = await driver.execute_query(query, uuid=request.episode_uuid)

        if not records:
            return PromotionResult(
                success=False,
                message=f"Episode not found: {request.episode_uuid}",
            )

        source_desc = records[0]["source_desc"] or ""

        # Check current status
        if "status:canonical" in source_desc:
            return PromotionResult(
                success=True,
                promoted=False,
                episode_uuid=request.episode_uuid,
                message="Learning is already canonical",
                previous_status="canonical",
                new_status="canonical",
            )

        # Update to canonical
        if "status:provisional" in source_desc:
            new_source_desc = source_desc.replace("status:provisional", "status:canonical")
            previous_status = "provisional"
        else:
            new_source_desc = f"{source_desc} status:canonical"
            previous_status = "unknown"

        # Add promotion reason if provided
        if request.reason:
            new_source_desc = f"{new_source_desc} promoted:{request.reason}"

        await _update_edge_source_description(request.episode_uuid, new_source_desc)

        logger.info(
            "Manually promoted learning %s to canonical (reason: %s)",
            request.episode_uuid,
            request.reason or "none",
        )

        return PromotionResult(
            success=True,
            promoted=True,
            episode_uuid=request.episode_uuid,
            message="Learning promoted to canonical",
            previous_status=previous_status,
            new_status="canonical",
        )

    except Exception as e:
        logger.error("Failed to promote learning: %s", e)
        return PromotionResult(
            success=False,
            message=f"Promotion failed: {e}",
        )


async def get_canonical_context(
    query: str,
    max_facts: int = 10,
    include_provisional: bool = False,
) -> list[str]:
    """
    Get context from canonical learnings (optionally include provisional).

    Args:
        query: Query to find relevant context
        max_facts: Maximum facts to return
        include_provisional: Whether to include provisional learnings

    Returns:
        List of relevant facts from canonical (and optionally provisional) learnings
    """
    graphiti = get_graphiti()
    facts: list[str] = []

    try:
        edges = await graphiti.search(
            query=query,
            group_ids=["global"],
            num_results=max_facts * 2,  # Fetch extra to filter
        )

        for edge in edges:
            if len(facts) >= max_facts:
                break

            source_desc = getattr(edge, "source_description", "") or ""

            # Filter by status
            is_canonical = "status:canonical" in source_desc
            is_provisional = "status:provisional" in source_desc

            if is_canonical or (include_provisional and is_provisional):
                fact = edge.fact
                if fact:
                    facts.append(fact)

    except Exception as e:
        logger.error("Failed to get canonical context: %s", e)

    return facts


async def _update_edge_source_description(uuid: str, new_source_desc: str) -> None:
    """Update the source_description field on an edge."""
    graphiti = get_graphiti()
    driver = graphiti.driver

    query = """
    MATCH (e:EntityEdge {uuid: $uuid})
    SET e.source_description = $source_desc
    """
    await driver.execute_query(query, uuid=uuid, source_desc=new_source_desc)


def _extract_confidence(source_desc: str) -> float:
    """Extract confidence value from source description."""
    import re

    match = re.search(r"confidence:(\d+(?:\.\d+)?)", source_desc)
    if match:
        return float(match.group(1))
    return 70.0  # Default to provisional threshold
