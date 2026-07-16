"""
Block retrieval functions for context injection.

Handles retrieval of mandates, guardrails, and reference blocks
using the PostgreSQL MemoryRepository.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from .context_injector_blocks_helpers import (
    episode_to_result,
    guardrail_episode_to_result,
    mandate_episode_to_result,
)
from .context_injector_queries import (
    get_auto_inject_references,
    get_episodes_by_tier,
    get_pinned_episodes_by_tier,
)
from .repository import MemoryRepository, get_memory_repository
from .service import MemoryScope, MemorySearchResult

logger = logging.getLogger(__name__)


class RequiredPolicyConversionError(RuntimeError):
    """An active mandate/guardrail could not become a delivered policy block."""


def _required_source_id(episode: dict) -> str:
    return str(episode.get("uuid") or episode.get("id") or "unknown")


async def get_mandates(
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
    db: AsyncSession | None = None,
) -> list[MemorySearchResult]:
    """Get all active mandates for a scope without usage-based demotion.

    Review/governance owns mandate authority. Citation or load counters are
    observability signals and must never silently remove operator policy.
    """
    episodes = await get_episodes_by_tier("mandate", scope, scope_id, db=db)
    logger.debug("Retrieved %d mandate episodes", len(episodes))

    results: list[MemorySearchResult] = []
    invalid_ids: list[str] = []
    for episode in episodes:
        result = mandate_episode_to_result(episode)
        if result is None:
            invalid_ids.append(_required_source_id(episode))
        else:
            results.append(result)
    if invalid_ids:
        raise RequiredPolicyConversionError(
            "Active mandates failed validation/conversion: " + ", ".join(invalid_ids)
        )

    logger.info("Mandate injection: %d/%d included", len(results), len(episodes))
    return results


async def get_guardrails(
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
    db: AsyncSession | None = None,
) -> list[MemorySearchResult]:
    """Get all guardrails for a scope (deterministic injection).

    Uses injection_tier='guardrail' field for filtering.
    Returns ALL guardrails — no scoring or thresholds.
    """
    episodes = await get_episodes_by_tier("guardrail", scope, scope_id, db=db)
    logger.debug("Retrieved %d guardrail episodes", len(episodes))

    results: list[MemorySearchResult] = []
    invalid_ids: list[str] = []
    for episode in episodes:
        try:
            result = guardrail_episode_to_result(episode)
        except Exception as exc:
            raise RequiredPolicyConversionError(
                f"Active guardrail {_required_source_id(episode)} failed validation/conversion: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        if result is None:
            invalid_ids.append(_required_source_id(episode))
        else:
            results.append(result)
    if invalid_ids:
        raise RequiredPolicyConversionError(
            "Active guardrails failed validation/conversion: " + ", ".join(invalid_ids)
        )

    logger.info("Guardrail injection: %d included", len(results))
    return results


async def get_auto_inject_references_as_search_results(
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
    db: AsyncSession | None = None,
) -> list[MemorySearchResult]:
    """Get auto-inject references as MemorySearchResult objects.

    References with auto_inject=true are injected like mandates/guardrails
    but kept in the reference block for organizational clarity.
    """
    episodes = await get_auto_inject_references(scope, scope_id, db=db)
    logger.debug("Retrieved %d auto-inject reference episodes", len(episodes))

    results = [r for ep in episodes if (r := episode_to_result(ep))]

    logger.info("Auto-inject reference injection: %d included", len(results))
    return results


async def get_pinned_episodes_as_search_results(
    tier: str,
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
    db: AsyncSession | None = None,
) -> list[MemorySearchResult]:
    """Get pinned episodes for a tier as search results.

    These bypass narrower retrieval rules so pinning really means "always show"
    whenever the memory system and that category are enabled.
    """
    episodes = await get_pinned_episodes_by_tier(tier, scope, scope_id, db=db)
    logger.debug("Retrieved %d pinned %s episodes", len(episodes), tier)

    results = [r for ep in episodes if (r := episode_to_result(ep))]

    logger.info("Pinned %s injection: %d included", tier, len(results))
    return results


async def get_triggered_references_as_search_results(
    task_type: str,
    group_id: str = "global",
    db: AsyncSession | None = None,
) -> list[MemorySearchResult]:
    """Get triggered references as MemorySearchResult objects.

    References with matching trigger_task_types are injected based on task context.
    """
    repo = get_memory_repository()
    memories = await repo.get_triggered_references(task_type, group_id=group_id, db=db)
    logger.debug(
        "Retrieved %d triggered reference episodes for task_type=%s", len(memories), task_type
    )

    results = [
        r
        for mem in memories
        if (r := episode_to_result(MemoryRepository._to_dict(mem)))
    ]

    logger.info(
        "Triggered reference injection for task_type=%s: %d included", task_type, len(results)
    )
    return results


async def get_phase_triggered_references_as_search_results(
    phase: str,
    group_id: str = "global",
    db: AsyncSession | None = None,
) -> list[MemorySearchResult]:
    """Get phase-triggered references as MemorySearchResult objects.

    References with matching trigger_phases are injected based on subtask phase.
    """
    repo = get_memory_repository()
    memories = await repo.get_phase_triggered_references(phase, group_id=group_id, db=db)
    logger.debug(
        "Retrieved %d phase-triggered reference episodes for phase=%s", len(memories), phase
    )

    results = [
        r
        for mem in memories
        if (r := episode_to_result(MemoryRepository._to_dict(mem)))
    ]

    logger.info(
        "Phase-triggered reference injection for phase=%s: %d included", phase, len(results)
    )
    return results
