"""DB-backed persona/runtime prompt loaders and template renderers."""

from __future__ import annotations

from app.services.prompt_catalog import (
    COMPLETION_REVIEW_PROMPT_SLUG,
    COMPLETION_REVIEW_RULES_PROMPT_SLUG,
    PERSONA_EVOLUTION_GUIDELINES_PROMPT_SLUG,
    PERSONA_FOCUS_HARNESS_PROMPT_SLUG,
    PERSONA_IMPROVEMENT_REVIEW_PROMPT_SLUG,
    PERSONA_ONBOARDING_BOOTSTRAP_PROMPT_SLUG,
    PERSONA_ONBOARDING_CONTINUATION_PROMPT_SLUG,
    PERSONA_ONBOARDING_PENDING_APPROVAL_PROMPT_SLUG,
    PERSONA_ONBOARDING_REVIEW_PROMPT_SLUG,
    PERSONA_WAKE_GUIDANCE_PROMPT_SLUG,
)
from app.services.prompt_service import require_prompt_content


async def get_persona_focus_harness() -> str:
    return await require_prompt_content(PERSONA_FOCUS_HARNESS_PROMPT_SLUG)


async def get_persona_wake_guidance() -> str:
    return await require_prompt_content(PERSONA_WAKE_GUIDANCE_PROMPT_SLUG)


async def get_persona_evolution_guidelines() -> str:
    return await require_prompt_content(PERSONA_EVOLUTION_GUIDELINES_PROMPT_SLUG)


async def render_persona_improvement_prompt(
    *,
    iteration: int,
    ranking_block: str,
    failure_block: str,
    persistent_block: str,
    new_block: str,
    resolved_block: str,
    review_ranking_block: str,
    review_failure_block: str,
    review_persistent_block: str,
    improvement_signals_block: str,
    field_signals_block: str,
    reference_block: str,
) -> str:
    template = await require_prompt_content(PERSONA_EVOLUTION_GUIDELINES_PROMPT_SLUG)
    return template.format(
        iteration=iteration,
        ranking_block=ranking_block.strip() or "- none",
        failure_block=failure_block.strip() or "Top failure clusters:\n- none",
        persistent_block=persistent_block.strip() or (
            "Persistent unresolved clusters from the previous iteration:\n- none"
        ),
        new_block=new_block.strip() or "New clusters this iteration:\n- none",
        resolved_block=resolved_block.strip() or "Resolved clusters since the previous iteration:\n- none",
        review_ranking_block=review_ranking_block.strip() or "- not run",
        review_failure_block=review_failure_block.strip() or "Completion-review failure clusters:\n- not run",
        review_persistent_block=review_persistent_block.strip() or (
            "Persistent completion-review clusters from the previous iteration:\n- not run"
        ),
        improvement_signals_block=improvement_signals_block.strip() or "- none",
        field_signals_block=field_signals_block.strip() or "- none",
        reference_block=reference_block.strip() or "- none",
    )


async def render_persona_improvement_decision_review_prompt(
    *,
    proposed_decision: str,
    proposed_reason: str,
    experiment_summary_block: str,
    completion_review_block: str,
    field_signals_block: str,
    improvement_summary_block: str,
) -> str:
    template = await require_prompt_content(PERSONA_IMPROVEMENT_REVIEW_PROMPT_SLUG)
    return template.format(
        proposed_decision=proposed_decision.strip() or "hold",
        proposed_reason=proposed_reason.strip() or "no_clear_winner",
        experiment_summary_block=experiment_summary_block.strip() or "- not available",
        completion_review_block=completion_review_block.strip() or "- not run",
        field_signals_block=field_signals_block.strip() or "- none",
        improvement_summary_block=improvement_summary_block.strip() or "- none",
    )


async def render_persona_onboarding_bootstrap(persona_name: str, *, has_prior_context: bool) -> str:
    template = await require_prompt_content(PERSONA_ONBOARDING_BOOTSTRAP_PROMPT_SLUG)
    prior_context_note = ""
    if has_prior_context:
        prior_context_note = (
            "\n\n**Note:** Previous user context exists from an earlier onboarding. "
            "Call `read_user_context` to review it before starting — you can build on "
            "what's already there rather than re-asking everything."
        )
    return template.format(
        persona_name=persona_name,
        prior_context_note=prior_context_note,
    )


async def render_persona_onboarding_continuation(persona_name: str) -> str:
    template = await require_prompt_content(PERSONA_ONBOARDING_CONTINUATION_PROMPT_SLUG)
    return template.format(persona_name=persona_name)


async def get_persona_onboarding_pending_approval() -> str:
    return await require_prompt_content(PERSONA_ONBOARDING_PENDING_APPROVAL_PROMPT_SLUG)


async def render_persona_onboarding_review_prompt(persona_name: str, profile_text: str) -> str:
    template = await require_prompt_content(PERSONA_ONBOARDING_REVIEW_PROMPT_SLUG)
    return template.format(persona_name=persona_name, profile_text=profile_text)


async def render_completion_review_rules(*, header: str = "Rules") -> str:
    body = await require_prompt_content(COMPLETION_REVIEW_RULES_PROMPT_SLUG)
    return header + ":\n" + body.strip()


async def render_completion_review_prompt(
    *,
    completion_content: str,
    cleanup_status: str,
    workstream_inventory: str,
) -> str:
    template = await require_prompt_content(COMPLETION_REVIEW_PROMPT_SLUG)
    review_rules = await render_completion_review_rules()
    return template.format(
        review_rules=review_rules,
        completion_content=completion_content.strip() or "(empty)",
        cleanup_status=cleanup_status.strip() or "(none)",
        workstream_inventory=workstream_inventory.strip() or "(none)",
    )


__all__ = [
    "get_persona_evolution_guidelines",
    "get_persona_focus_harness",
    "get_persona_onboarding_pending_approval",
    "get_persona_wake_guidance",
    "render_completion_review_prompt",
    "render_completion_review_rules",
    "render_persona_improvement_decision_review_prompt",
    "render_persona_improvement_prompt",
    "render_persona_onboarding_bootstrap",
    "render_persona_onboarding_continuation",
    "render_persona_onboarding_review_prompt",
]
