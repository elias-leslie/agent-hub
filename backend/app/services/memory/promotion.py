"""
Memory promotion service for reinforcement-based learning.

Implements the two-state system (per decision d2):
- provisional: 70-89 confidence, needs reinforcement
- canonical: 90+ confidence, trusted

Promotion happens when:
1. A new learning semantically matches an existing provisional learning
2. Manual promotion via API

Uses MemoryRepository (PostgreSQL + pgvector).
"""

import logging
import re

from pydantic import BaseModel, Field

from .learning_constants import CANONICAL_THRESHOLD
from .repository import get_memory_repository

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

    episode_uuid: str = Field(..., description="UUID of the memory to promote")
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
    query_embedding: list[float] | None = None,
    group_id: str | None = None,
) -> ReinforcementResult:
    """
    Check if a new learning matches an existing provisional learning.

    If a semantic match is found with a provisional learning, promote it to canonical.

    Args:
        content: The new learning content
        confidence: Confidence of the new learning
        query_embedding: Pre-computed embedding for semantic search
        group_id: Optional group_id filter

    Returns:
        ReinforcementResult indicating if promotion occurred
    """
    repo = get_memory_repository()
    result = ReinforcementResult()

    try:
        if not query_embedding:
            # Without an embedding we cannot do semantic search; fall back to text search
            matches = await repo.text_search(content, group_id=group_id, limit=5)
            candidates = [
                {
                    "uuid": str(m.id),
                    "source_description": m.source_description or "",
                    "relevance_score": 1.0,  # exact text match gets high score
                }
                for m in matches
            ]
        else:
            candidates = await repo.semantic_search(
                query_embedding,
                group_id=group_id,
                limit=5,
            )

        if not candidates:
            return result

        for candidate in candidates:
            score = candidate.get("relevance_score", 0.0)
            if score < SIMILARITY_THRESHOLD:
                continue

            source_desc = candidate.get("source_description", "") or ""
            if "status:provisional" not in source_desc:
                continue

            # Found a matching provisional learning — promote it
            result.found_match = True
            matched_uuid = candidate.get("uuid", "")
            result.matched_uuid = matched_uuid

            # Calculate new confidence (average of existing + new, capped at 100)
            existing_conf = _extract_confidence(source_desc)
            new_conf = min(100, (existing_conf + confidence) / 2 + 10)
            result.new_confidence = new_conf

            if new_conf >= CANONICAL_THRESHOLD:
                new_source_desc = source_desc.replace(
                    "status:provisional", "status:canonical"
                ).replace(f"confidence:{existing_conf:.0f}", f"confidence:{new_conf:.0f}")

                await repo.update(matched_uuid, source_description=new_source_desc)
                result.promoted = True

                logger.info(
                    "Promoted learning %s from provisional to canonical "
                    "(old_conf=%.0f, new_conf=%.0f)",
                    matched_uuid[:8],
                    existing_conf,
                    new_conf,
                )
            else:
                new_source_desc = source_desc.replace(
                    f"confidence:{existing_conf:.0f}", f"confidence:{new_conf:.0f}"
                )
                await repo.update(matched_uuid, source_description=new_source_desc)

                logger.info(
                    "Reinforced provisional learning %s (old_conf=%.0f, new_conf=%.0f)",
                    matched_uuid[:8],
                    existing_conf,
                    new_conf,
                )

            return result  # Only process first match

    except Exception as e:
        from .exceptions import PromotionError

        logger.error("Failed to check for duplicate learnings: %s", e)
        if isinstance(e, PromotionError):
            raise

    return result


async def promote_learning(request: PromoteRequest) -> PromotionResult:
    """
    Manually promote a learning to canonical status.

    Args:
        request: Promotion request with memory UUID

    Returns:
        PromotionResult indicating success
    """
    repo = get_memory_repository()

    try:
        mem = await repo.get_as_dict(request.episode_uuid)
        if not mem:
            return PromotionResult(
                success=False,
                message=f"Memory not found: {request.episode_uuid}",
            )

        source_desc = mem.get("source_description", "") or ""

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

        await repo.update(request.episode_uuid, source_description=new_source_desc)

        logger.info(
            "Manually promoted learning %s to canonical (reason: %s)",
            request.episode_uuid[:8],
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
        from .exceptions import PromotionError

        logger.error("Failed to promote learning: %s", e)
        if isinstance(e, PromotionError):
            raise
        return PromotionResult(
            success=False,
            message=f"Promotion failed: {e}",
        )


async def get_canonical_context(
    query: str,
    max_facts: int = 10,
    include_provisional: bool = False,
    query_embedding: list[float] | None = None,
    group_id: str | None = None,
) -> list[str]:
    """
    Get context from canonical learnings (optionally include provisional).

    Args:
        query: Query to find relevant context
        max_facts: Maximum facts to return
        include_provisional: Whether to include provisional learnings
        query_embedding: Pre-computed embedding for semantic search
        group_id: Optional group_id filter

    Returns:
        List of relevant facts from canonical (and optionally provisional) learnings
    """
    repo = get_memory_repository()
    facts: list[str] = []

    try:
        if query_embedding:
            candidates = await repo.semantic_search(
                query_embedding,
                group_id=group_id,
                limit=max_facts * 2,
            )
        else:
            matches = await repo.text_search(query, group_id=group_id, limit=max_facts * 2)
            candidates = [
                {
                    "content": m.content,
                    "source_description": m.source_description or "",
                }
                for m in matches
            ]

        for candidate in candidates:
            if len(facts) >= max_facts:
                break

            source_desc = candidate.get("source_description", "") or ""
            is_canonical = "status:canonical" in source_desc
            is_provisional = "status:provisional" in source_desc

            if is_canonical or (include_provisional and is_provisional):
                content = candidate.get("content", "")
                if content:
                    facts.append(content)

    except Exception as e:
        from .exceptions import PromotionError

        logger.error("Failed to get canonical context: %s", e)
        if isinstance(e, PromotionError):
            raise

    return facts


def _extract_confidence(source_desc: str) -> float:
    """Extract confidence value from source description."""
    match = re.search(r"confidence:(\d+(?:\.\d+)?)", source_desc)
    if match:
        return float(match.group(1))
    return 70.0  # Default to provisional threshold
