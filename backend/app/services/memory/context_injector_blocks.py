"""
Block retrieval functions for context injection.

Handles retrieval of mandates, guardrails, and reference blocks.
"""

import logging
from datetime import UTC, datetime

from .context_injector_queries import get_auto_inject_references, get_episodes_by_tier
from .graphiti_client import get_phase_triggered_references, get_triggered_references
from .service import MemoryScope, MemorySearchResult, MemorySource

logger = logging.getLogger(__name__)


async def get_mandates(
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
) -> list[MemorySearchResult]:
    """
    Get all mandates for a scope (deterministic injection).

    Uses injection_tier='mandate' field for filtering.
    Returns ALL non-demoted mandates - no scoring or thresholds.
    Mandates are critical system knowledge that must always be injected.

    Args:
        scope: Memory scope to query
        scope_id: Project or task ID for scoping

    Returns:
        List of all non-demoted mandate search results
    """
    from .adaptive_index import get_adaptive_index

    # Get adaptive index for demotion logic only
    adaptive_index = await get_adaptive_index()
    demoted_uuids = {e.uuid for e in adaptive_index.entries if e.is_demoted}

    # Get mandates by injection_tier field
    episodes = await get_episodes_by_tier("mandate", scope, scope_id)
    logger.debug("Retrieved %d mandate episodes", len(episodes))

    results: list[MemorySearchResult] = []
    for ep in episodes:
        content = ep.get("content") or ""
        uuid = ep.get("uuid", "")
        if not content:
            logger.debug("Skipping mandate without content: %s", uuid[:8] if uuid else "?")
            continue

        # Check if demoted by adaptive index
        if uuid in demoted_uuids:
            logger.debug("Excluding demoted mandate: uuid=%s", uuid[:8])
            continue

        # Convert neo4j.time.DateTime to Python datetime if needed
        created_at = ep.get("created_at")
        if created_at is not None and hasattr(created_at, "to_native"):
            created_at = created_at.to_native()
        if not isinstance(created_at, datetime):
            created_at = datetime.now(UTC)

        try:
            results.append(
                MemorySearchResult(
                    uuid=uuid,
                    content=content,
                    source=MemorySource.SYSTEM,
                    relevance_score=1.0,  # All mandates are equally important
                    created_at=created_at,
                    facts=[content],
                    pinned=ep.get("pinned", False),
                )
            )
        except Exception as e:
            logger.warning(
                "Failed to create MemorySearchResult: %s (content=%s...)", e, content[:50]
            )

    logger.info(
        "Mandate injection: %d/%d included (demoted=%d)",
        len(results),
        len(episodes),
        len(demoted_uuids),
    )
    return results


async def get_guardrails(
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
) -> list[MemorySearchResult]:
    """
    Get all guardrails for a scope (deterministic injection).

    Uses injection_tier='guardrail' field for filtering.
    Returns ALL guardrails - no scoring or thresholds.
    Guardrails are anti-patterns that must always be injected.

    Args:
        scope: Memory scope to query
        scope_id: Project or task ID for scoping

    Returns:
        List of all guardrail search results
    """
    # Get guardrails by injection_tier field
    episodes = await get_episodes_by_tier("guardrail", scope, scope_id)
    logger.debug("Retrieved %d guardrail episodes", len(episodes))

    results: list[MemorySearchResult] = []

    for ep in episodes:
        content = ep.get("content") or ""
        uuid = ep.get("uuid", "")

        if not content:
            continue

        # Convert neo4j.time.DateTime to Python datetime if needed
        created_at = ep.get("created_at")
        if created_at is not None and hasattr(created_at, "to_native"):
            created_at = created_at.to_native()
        if not isinstance(created_at, datetime):
            created_at = datetime.now(UTC)

        results.append(
            MemorySearchResult(
                uuid=uuid,
                content=content,
                source=MemorySource.SYSTEM,
                relevance_score=1.0,  # All guardrails are equally important
                created_at=created_at,
                facts=[content],
            )
        )

    logger.info("Guardrail injection: %d included", len(results))
    return results


async def get_auto_inject_references_as_search_results(
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
) -> list[MemorySearchResult]:
    """
    Get auto-inject references as MemorySearchResult objects.

    References with auto_inject=true are injected like mandates/guardrails
    but kept in the reference block for organizational clarity.

    Args:
        scope: Memory scope to query
        scope_id: Project or task ID for scoping

    Returns:
        List of auto-inject reference search results
    """
    episodes = await get_auto_inject_references(scope, scope_id)
    logger.debug("Retrieved %d auto-inject reference episodes", len(episodes))

    results: list[MemorySearchResult] = []
    for ep in episodes:
        content = ep.get("content") or ""
        uuid = ep.get("uuid", "")
        if not content:
            continue

        created_at = ep.get("created_at")
        if created_at is not None and hasattr(created_at, "to_native"):
            created_at = created_at.to_native()
        if not isinstance(created_at, datetime):
            created_at = datetime.now(UTC)

        results.append(
            MemorySearchResult(
                uuid=uuid,
                content=content,
                source=MemorySource.SYSTEM,
                relevance_score=1.0,
                created_at=created_at,
                facts=[content],
            )
        )

    logger.info("Auto-inject reference injection: %d included", len(results))
    return results


async def get_triggered_references_as_search_results(
    task_type: str,
    group_id: str = "global",
) -> list[MemorySearchResult]:
    """
    Get triggered references as MemorySearchResult objects.

    References with matching trigger_task_types are injected based on task context.

    Args:
        task_type: Task type to match against trigger_task_types
        group_id: Group ID to filter episodes (default: global)

    Returns:
        List of triggered reference search results
    """
    episodes = await get_triggered_references(task_type, group_id)
    logger.debug(
        "Retrieved %d triggered reference episodes for task_type=%s", len(episodes), task_type
    )

    results: list[MemorySearchResult] = []
    for ep in episodes:
        content = ep.get("content") or ""
        uuid = ep.get("uuid", "")
        if not content:
            continue

        results.append(
            MemorySearchResult(
                uuid=uuid,
                content=content,
                source=MemorySource.SYSTEM,
                relevance_score=1.0,
                created_at=datetime.now(UTC),
                facts=[content],
            )
        )

    logger.info(
        "Triggered reference injection for task_type=%s: %d included", task_type, len(results)
    )
    return results


async def get_phase_triggered_references_as_search_results(
    phase: str,
    group_id: str = "global",
) -> list[MemorySearchResult]:
    """
    Get phase-triggered references as MemorySearchResult objects.

    References with matching trigger_phases are injected based on subtask phase.

    Args:
        phase: Phase to match against trigger_phases (e.g., planning, implementation, review)
        group_id: Group ID to filter episodes (default: global)

    Returns:
        List of phase-triggered reference search results
    """
    episodes = await get_phase_triggered_references(phase, group_id)
    logger.debug(
        "Retrieved %d phase-triggered reference episodes for phase=%s", len(episodes), phase
    )

    results: list[MemorySearchResult] = []
    for ep in episodes:
        content = ep.get("content") or ""
        uuid = ep.get("uuid", "")
        if not content:
            continue

        results.append(
            MemorySearchResult(
                uuid=uuid,
                content=content,
                source=MemorySource.SYSTEM,
                relevance_score=1.0,
                created_at=datetime.now(UTC),
                facts=[content],
            )
        )

    logger.info(
        "Phase-triggered reference injection for phase=%s: %d included", phase, len(results)
    )
    return results
