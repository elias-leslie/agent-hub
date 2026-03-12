"""Helper functions for memory agent handlers."""

from app.services.memory.context_injector import ProgressiveContext
from app.services.memory.service import MemoryScope

from .memory_agent_schemas import SaveLearningResponse, ScoringBreakdown
from .memory_schemas import BudgetUsageResponse


async def build_reference_episodes(
    scope: MemoryScope,
    scope_id: str | None,
) -> list[tuple[str, str | None, str, bool]] | None:
    """Build reference TOON index if enabled."""
    from app.services.memory.context_injector import build_reference_toon_index
    from app.services.memory.settings import get_memory_settings

    settings = await get_memory_settings()
    if not settings.reference_index_enabled:
        return None

    # Always include global scope references
    reference_episodes = await build_reference_toon_index(MemoryScope.GLOBAL, None)

    # Add project-specific references if project scope requested
    if scope == MemoryScope.PROJECT and scope_id:
        project_refs = await build_reference_toon_index(scope, scope_id)
        if project_refs:
            # Dedupe by UUID (global first, then project)
            seen_uuids = {r[0] for r in reference_episodes}
            reference_episodes.extend(r for r in project_refs if r[0] not in seen_uuids)

    return reference_episodes


def build_scoring_breakdown(context: ProgressiveContext) -> list[ScoringBreakdown]:
    """Build scoring breakdown for debug mode."""
    scoring_breakdown = []

    for m in context.mandates:
        scoring_breakdown.append(
            ScoringBreakdown(
                uuid=m.uuid[:8] if m.uuid else "unknown",
                score=m.relevance_score,
                semantic=m.relevance_score,
                content_preview=m.content[:60] + "..." if len(m.content) > 60 else m.content,
            )
        )

    for g in context.guardrails:
        scoring_breakdown.append(
            ScoringBreakdown(
                uuid=g.uuid[:8] if g.uuid else "unknown",
                score=g.relevance_score,
                semantic=g.relevance_score,
                content_preview=g.content[:60] + "..." if len(g.content) > 60 else g.content,
            )
        )

    for r in context.reference:
        scoring_breakdown.append(
            ScoringBreakdown(
                uuid=r.uuid[:8] if r.uuid else "unknown",
                score=r.relevance_score,
                semantic=r.relevance_score,
                content_preview=r.content[:60] + "..." if len(r.content) > 60 else r.content,
            )
        )

    return scoring_breakdown


def build_budget_usage(context: ProgressiveContext) -> BudgetUsageResponse | None:
    """Build budget usage response from context."""
    if not context.budget_usage:
        return None

    return BudgetUsageResponse(
        mandates_tokens=context.budget_usage.mandates_tokens,
        guardrails_tokens=context.budget_usage.guardrails_tokens,
        reference_tokens=context.budget_usage.reference_tokens,
        continuity_tokens=context.budget_usage.continuity_tokens,
        total_tokens=context.budget_usage.total_tokens,
        total_budget=context.budget_usage.total_budget,
        remaining=context.budget_usage.remaining,
        hit_limit=context.budget_usage.hit_limit,
        mandates_injected=len(context.mandates),
        guardrails_injected=len(context.guardrails),
        reference_injected=len(context.reference),
        mandates_total=context.budget_usage.mandates_total,
        guardrails_total=context.budget_usage.guardrails_total,
        reference_total=context.budget_usage.reference_total,
    )


async def check_duplicate(content: str, confidence: int) -> SaveLearningResponse | None:
    """Check for duplicate learning and return response if found."""
    from app.services.memory.promotion import check_and_promote_duplicate

    try:
        reinforcement = await check_and_promote_duplicate(
            content=content,
            confidence=confidence,
        )

        if reinforcement.found_match:
            status = "canonical" if reinforcement.promoted else "provisional"
            return SaveLearningResponse(
                uuid=None,
                status=status,
                is_duplicate=True,
                reinforced_uuid=reinforcement.matched_uuid,
                message=f"Reinforced existing learning (new confidence: {reinforcement.new_confidence}%)",
            )
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning("Duplicate check failed: %s", e)

    return None


async def set_episode_properties(
    uuid: str,
    pinned: bool,
    trigger_task_types: list[str] | None,
    *,
    change_reason: str | None = None,
) -> None:
    """Set additional properties on episode if provided."""
    if not uuid or (not pinned and not trigger_task_types):
        return

    from app.services.memory.episode_property_setters import (
        set_episode_pinned,
        set_episode_trigger_task_types,
    )

    if pinned:
        await set_episode_pinned(uuid, True, change_reason=change_reason)
    if trigger_task_types:
        await set_episode_trigger_task_types(uuid, trigger_task_types, change_reason=change_reason)
