"""Helper functions for memory agent handlers."""

from app.services.memory.context_injector import ProgressiveContext

from .memory_agent_schemas import SaveLearningResponse, ScoringBreakdown
from .memory_schemas import BudgetUsageResponse


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
    trigger_phases: list[str] | None,
    context_kind: str | None,
    applicability: dict[str, object] | None,
    *,
    change_reason: str | None = None,
    render_mode: str | None = None,
) -> None:
    """Set additional properties on episode if provided."""
    if not uuid or (
        not pinned
        and not trigger_task_types
        and not trigger_phases
        and not context_kind
        and not applicability
        and render_mode is None
    ):
        return

    from app.services.memory.episode_property_setters import (
        set_episode_applicability,
        set_episode_context_kind,
        set_episode_pinned,
        set_episode_render_mode,
        set_episode_trigger_phases,
        set_episode_trigger_task_types,
    )

    if pinned:
        await set_episode_pinned(uuid, True, change_reason=change_reason)
    if trigger_task_types:
        await set_episode_trigger_task_types(uuid, trigger_task_types, change_reason=change_reason)
    if trigger_phases:
        await set_episode_trigger_phases(uuid, trigger_phases, change_reason=change_reason)
    if context_kind:
        await set_episode_context_kind(uuid, context_kind, change_reason=change_reason)
    if applicability is not None:
        await set_episode_applicability(uuid, applicability, change_reason=change_reason)
    if render_mode is not None:
        await set_episode_render_mode(uuid, render_mode, change_reason=change_reason)
