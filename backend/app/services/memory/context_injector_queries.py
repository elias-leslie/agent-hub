"""
Episode retrieval queries for context injection.

Handles database queries for episodes by tier and injection rules.
"""

import logging
from typing import Any

from .graphiti_client import get_graphiti
from .service import MemoryScope, build_group_id

logger = logging.getLogger(__name__)


async def get_episodes_by_tier(
    tier: str,
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Get episodes by injection_tier field.

    This is the new tier-first query method that replaces keyword matching.

    Args:
        tier: The injection tier (mandate/guardrail/reference)
        scope: Memory scope to query
        scope_id: Project or task ID for scoping

    Returns:
        List of episode dicts with uuid, content, created_at, etc.
    """
    graphiti = get_graphiti()
    driver = graphiti.driver
    group_id = build_group_id(scope, scope_id)

    query = """
    MATCH (e:Episodic {group_id: $group_id})
    WHERE e.injection_tier = $tier
      AND COALESCE(e.vector_indexed, true) = true
    RETURN e.uuid AS uuid,
           e.content AS content,
           e.name AS name,
           e.summary AS summary,
           e.source_description AS source_description,
           e.created_at AS created_at,
           COALESCE(e.loaded_count, 0) AS loaded_count,
           COALESCE(e.referenced_count, 0) AS referenced_count,
           COALESCE(e.utility_score, 0.5) AS utility_score,
           COALESCE(e.pinned, false) AS pinned,
           COALESCE(e.auto_inject, false) AS auto_inject,
           COALESCE(e.display_order, 50) AS display_order
    ORDER BY COALESCE(e.display_order, 50) ASC,
             COALESCE(e.utility_score, 0.5) DESC,
             COALESCE(e.referenced_count, 0) DESC,
             e.created_at DESC
    """

    try:
        records, _, _ = await driver.execute_query(
            query,
            group_id=group_id,
            tier=tier,
        )
        return [dict(r) for r in records]
    except Exception as e:
        logger.warning("Failed to get episodes by tier %s: %s", tier, e)
        return []


async def get_auto_inject_references(
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
) -> list[dict[str, Any]]:
    """
    Get reference-tier episodes with auto_inject=true.

    These are references that should be injected like mandates/guardrails,
    but are categorized separately for organizational purposes.

    Args:
        scope: Memory scope to query
        scope_id: Project or task ID for scoping

    Returns:
        List of auto-inject reference episode dicts
    """
    graphiti = get_graphiti()
    driver = graphiti.driver
    group_id = build_group_id(scope, scope_id)

    query = """
    MATCH (e:Episodic {group_id: $group_id})
    WHERE e.injection_tier = 'reference'
      AND e.auto_inject = true
      AND COALESCE(e.vector_indexed, true) = true
    RETURN e.uuid AS uuid,
           e.content AS content,
           e.name AS name,
           e.summary AS summary,
           e.source_description AS source_description,
           e.created_at AS created_at,
           COALESCE(e.loaded_count, 0) AS loaded_count,
           COALESCE(e.referenced_count, 0) AS referenced_count,
           COALESCE(e.utility_score, 0.5) AS utility_score,
           COALESCE(e.pinned, false) AS pinned,
           COALESCE(e.display_order, 50) AS display_order
    ORDER BY COALESCE(e.display_order, 50) ASC,
             COALESCE(e.utility_score, 0.5) DESC,
             e.created_at DESC
    """

    try:
        records, _, _ = await driver.execute_query(
            query,
            group_id=group_id,
        )
        return [dict(r) for r in records]
    except Exception as e:
        logger.warning("Failed to get auto-inject references: %s", e)
        return []


async def build_reference_toon_index(
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
) -> list[tuple[str, str | None, str, bool]]:
    """
    Get all reference-tier episodes for TOON index generation.

    Returns list of (uuid, summary, content, pinned) tuples for TOON formatting.
    Summary is used for display; content is fallback only.
    Pinned items are expanded to full content in format_context_with_reference_index.
    """
    episodes = await get_episodes_by_tier("reference", scope, scope_id)
    return [
        (ep.get("uuid", ""), ep.get("summary"), ep.get("content", ""), ep.get("pinned", False))
        for ep in episodes
        if ep.get("uuid") and ep.get("content")
    ]
