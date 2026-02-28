"""Redundancy detection via pgvector cosine similarity.

Thresholds:
  >= 0.97 similarity: Auto-consolidate (merge stats, subordinate archived)
  0.92-0.97: Log suggestion to tier_change_log, no auto-action
  < 0.92: Not redundant

Rules:
  - Never auto-consolidate pinned memories
  - Survivor = higher lifecycle_score, then higher tier, then newer
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from app.db import async_session
from app.models.memory_unified import Memory

from ._repo_helpers import TIER_REVERSE
from .tier_operations import log_tier_change

logger = logging.getLogger(__name__)

AUTO_CONSOLIDATE_THRESHOLD = 0.97
SUGGESTION_THRESHOLD = 0.92


async def find_redundant_pairs(
    *,
    min_similarity: float = SUGGESTION_THRESHOLD,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Find near-duplicate memory pairs using pgvector cosine similarity.

    Returns pairs sorted by similarity (highest first).
    Only considers active memories with embeddings.
    """
    # Use pgvector's cosine distance operator: 1 - (a <=> b) = cosine similarity
    # Self-join with id constraint to avoid (A,A) and get each pair once
    query = text("""
        SELECT
            a.id AS id_a,
            a.name AS name_a,
            a.tier AS tier_a,
            a.lifecycle_score AS score_a,
            a.pinned AS pinned_a,
            b.id AS id_b,
            b.name AS name_b,
            b.tier AS tier_b,
            b.lifecycle_score AS score_b,
            b.pinned AS pinned_b,
            1 - (a.embedding <=> b.embedding) AS similarity
        FROM memories a
        JOIN memories b ON a.id < b.id
        WHERE a.status = 'active'
          AND b.status = 'active'
          AND a.embedding IS NOT NULL
          AND b.embedding IS NOT NULL
          AND 1 - (a.embedding <=> b.embedding) >= :min_similarity
        ORDER BY similarity DESC
        LIMIT :limit
    """)

    async with async_session() as session:
        result = await session.execute(
            query, {"min_similarity": min_similarity, "limit": limit}
        )
        rows = result.all()

    pairs = []
    for row in rows:
        pairs.append({
            "id_a": str(row.id_a),
            "name_a": row.name_a,
            "tier_a": TIER_REVERSE.get(row.tier_a, "reference"),
            "score_a": row.score_a,
            "pinned_a": row.pinned_a,
            "id_b": str(row.id_b),
            "name_b": row.name_b,
            "tier_b": TIER_REVERSE.get(row.tier_b, "reference"),
            "score_b": row.score_b,
            "pinned_b": row.pinned_b,
            "similarity": round(float(row.similarity), 4),
        })
    return pairs


def _pick_survivor(pair: dict[str, Any]) -> tuple[str, str]:
    """Pick survivor and subordinate from a pair. Returns (survivor_id, subordinate_id).

    Priority: higher lifecycle_score > higher tier > newer (lower UUID = older by convention,
    but we use score as primary signal).
    """
    # Compare scores (higher wins)
    score_a = pair.get("score_a") or 0
    score_b = pair.get("score_b") or 0

    if score_a > score_b:
        return pair["id_a"], pair["id_b"]
    if score_b > score_a:
        return pair["id_b"], pair["id_a"]

    # Tie: higher tier wins (lower number = higher tier)
    tier_map = {"mandate": 1, "guardrail": 2, "reference": 3, "archive": 4}
    tier_a = tier_map.get(pair["tier_a"], 3)
    tier_b = tier_map.get(pair["tier_b"], 3)
    if tier_a < tier_b:
        return pair["id_a"], pair["id_b"]

    # Default: pick A as survivor
    return pair["id_a"], pair["id_b"]


async def find_and_consolidate_redundant() -> dict[str, Any]:
    """Run redundancy detection and auto-consolidate high-similarity pairs.

    - >= 0.97: Auto-consolidate (merge stats to survivor, archive subordinate)
    - 0.92-0.97: Log suggestion only

    Returns {consolidated, suggestions, details}.
    """
    results: dict[str, Any] = {"consolidated": 0, "suggestions": 0, "details": []}

    pairs = await find_redundant_pairs()
    if not pairs:
        return results

    for pair in pairs:
        # Never auto-consolidate pinned memories
        either_pinned = pair["pinned_a"] or pair["pinned_b"]

        if pair["similarity"] >= AUTO_CONSOLIDATE_THRESHOLD and not either_pinned:
            # Auto-consolidate
            survivor_id, subordinate_id = _pick_survivor(pair)
            await _consolidate_pair(survivor_id, subordinate_id, pair)
            results["consolidated"] += 1
            results["details"].append({
                "action": "consolidated",
                "survivor": survivor_id[:8],
                "subordinate": subordinate_id[:8],
                "similarity": pair["similarity"],
            })
        else:
            # Log suggestion
            reason = f"redundancy_suggestion: similarity={pair['similarity']:.4f}"
            if either_pinned:
                reason += " (pinned — no auto-action)"
            await log_tier_change(
                pair["id_a"],
                pair["tier_a"],
                pair["tier_a"],  # no change
                reason,
                "suggestion",
                metadata={
                    "pair_id": pair["id_b"],
                    "similarity": pair["similarity"],
                },
            )
            results["suggestions"] += 1
            results["details"].append({
                "action": "suggestion",
                "id_a": pair["id_a"][:8],
                "id_b": pair["id_b"][:8],
                "similarity": pair["similarity"],
            })

    logger.info(
        "Redundancy detection: %d consolidated, %d suggestions",
        results["consolidated"],
        results["suggestions"],
    )
    return results


async def _consolidate_pair(
    survivor_id: str,
    subordinate_id: str,
    pair: dict[str, Any],
) -> None:
    """Merge stats from subordinate into survivor and archive subordinate."""
    async with async_session() as session:
        # Fetch both
        survivor = await session.get(Memory, survivor_id)
        subordinate = await session.get(Memory, subordinate_id)

        if not survivor or not subordinate:
            logger.warning("Consolidation skipped — memory not found: %s / %s", survivor_id[:8], subordinate_id[:8])
            return

        # Merge counters
        survivor.loaded_count += subordinate.loaded_count
        survivor.referenced_count += subordinate.referenced_count
        survivor.helpful_count += subordinate.helpful_count
        survivor.harmful_count += subordinate.harmful_count

        # Archive subordinate
        subordinate.status = "archived"
        subordinate.superseded_by = survivor.id

        await session.commit()

    await log_tier_change(
        subordinate_id,
        pair.get("tier_b", "reference") if subordinate_id == pair["id_b"] else pair.get("tier_a", "reference"),
        "archive",
        f"consolidated: superseded by {survivor_id[:8]}, similarity={pair['similarity']:.4f}",
        "consolidation",
        metadata={
            "survivor_id": survivor_id,
            "similarity": pair["similarity"],
        },
    )
