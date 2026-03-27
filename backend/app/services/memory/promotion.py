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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_confidence(source_desc: str) -> float:
    """Extract confidence value from source description."""
    match = re.search(r"confidence:(\d+(?:\.\d+)?)", source_desc)
    if match:
        return float(match.group(1))
    return 70.0  # Default to provisional threshold


def _update_confidence_in_desc(source_desc: str, old_conf: float, new_conf: float) -> str:
    """Replace the confidence tag in source_desc with the new value."""
    return source_desc.replace(
        f"confidence:{old_conf:.0f}", f"confidence:{new_conf:.0f}"
    )


async def _fetch_candidates(
    repo,
    content: str,
    query_embedding: list[float] | None,
    group_id: str | None,
) -> list[dict]:
    """Return candidate records via semantic or text search."""
    if query_embedding:
        return await repo.semantic_search(query_embedding, group_id=group_id, limit=5)

    matches = await repo.text_search(content, group_id=group_id, limit=5)
    return [
        {
            "uuid": str(m.id),
            "source_description": m.source_description or "",
            "relevance_score": 1.0,
        }
        for m in matches
    ]


async def _apply_reinforcement(
    repo,
    candidate: dict,
    confidence: float,
) -> ReinforcementResult:
    """Promote or reinforce a matching provisional candidate. Returns updated result."""
    result = ReinforcementResult(found_match=True)
    matched_uuid = str(candidate.get("uuid", ""))
    result.matched_uuid = matched_uuid

    source_desc = str(candidate.get("source_description", "") or "")
    existing_conf = _extract_confidence(source_desc)
    new_conf = min(100, (existing_conf + confidence) / 2 + 10)
    result.new_confidence = new_conf

    updated_desc = _update_confidence_in_desc(source_desc, existing_conf, new_conf)

    if new_conf >= CANONICAL_THRESHOLD:
        updated_desc = updated_desc.replace("status:provisional", "status:canonical")
        result.promoted = True
        logger.info(
            "Promoted learning %s from provisional to canonical "
            "(old_conf=%.0f, new_conf=%.0f)",
            matched_uuid[:8],
            existing_conf,
            new_conf,
        )
    else:
        logger.info(
            "Reinforced provisional learning %s (old_conf=%.0f, new_conf=%.0f)",
            matched_uuid[:8],
            existing_conf,
            new_conf,
        )

    await repo.update(matched_uuid, source_description=updated_desc)
    return result


def _is_provisional_match(candidate: dict, score_threshold: float) -> bool:
    """Return True when candidate is provisional and meets the similarity threshold."""
    score = float(candidate.get("relevance_score", 0.0))
    if score < score_threshold:
        return False
    source_desc = str(candidate.get("source_description", "") or "")
    return "status:provisional" in source_desc


def _build_source_desc_for_promotion(source_desc: str, reason: str | None) -> tuple[str, str]:
    """
    Return (updated_source_desc, previous_status) for a manual promotion.

    Does not handle the already-canonical case.
    """
    if "status:provisional" in source_desc:
        updated = source_desc.replace("status:provisional", "status:canonical")
        previous_status = "provisional"
    else:
        updated = f"{source_desc} status:canonical"
        previous_status = "unknown"

    if reason:
        updated = f"{updated} promoted:{reason}"

    return updated, previous_status


def _candidate_qualifies_for_context(source_desc: str, include_provisional: bool) -> bool:
    """Return True if a candidate should be included in context results."""
    if "status:canonical" in source_desc:
        return True
    return include_provisional and "status:provisional" in source_desc


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


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

    try:
        candidates = await _fetch_candidates(repo, content, query_embedding, group_id)
        for candidate in candidates:
            if _is_provisional_match(candidate, SIMILARITY_THRESHOLD):
                return await _apply_reinforcement(repo, candidate, confidence)
    except Exception as e:
        from .exceptions import PromotionError

        logger.error("Failed to check for duplicate learnings: %s", e)
        if isinstance(e, PromotionError):
            raise

    return ReinforcementResult()


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
        memory_record = await repo.get_as_dict(request.episode_uuid)
        if not memory_record:
            return PromotionResult(
                success=False,
                message=f"Memory not found: {request.episode_uuid}",
            )

        source_desc = memory_record.get("source_description", "") or ""

        if "status:canonical" in source_desc:
            return PromotionResult(
                success=True,
                promoted=False,
                episode_uuid=request.episode_uuid,
                message="Learning is already canonical",
                previous_status="canonical",
                new_status="canonical",
            )

        updated_desc, previous_status = _build_source_desc_for_promotion(
            source_desc, request.reason
        )
        await repo.update(request.episode_uuid, source_description=updated_desc)

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
                query_embedding, group_id=group_id, limit=max_facts * 2
            )
        else:
            matches = await repo.text_search(query, group_id=group_id, limit=max_facts * 2)
            candidates = [
                {"content": m.content, "source_description": m.source_description or ""}
                for m in matches
            ]

        for candidate in candidates:
            if len(facts) >= max_facts:
                break
            source_desc = candidate.get("source_description", "") or ""
            content = candidate.get("content", "")
            if content and _candidate_qualifies_for_context(source_desc, include_provisional):
                facts.append(content)

    except Exception as e:
        from .exceptions import PromotionError

        logger.error("Failed to get canonical context: %s", e)
        if isinstance(e, PromotionError):
            raise

    return facts
