"""Jenny mutable state capture and restore."""
from __future__ import annotations

from app.db import async_session
from app.services.agent_service import get_agent_service
from app.services.persona_instruction_service import get_persona_heartbeat_instructions
from app.services.prompt_catalog import (
    COMPLETION_REVIEW_PROMPT_SLUG,
    COMPLETION_REVIEW_RULES_PROMPT_SLUG,
    PERSONA_HEARTBEAT_INSTRUCTIONS_PROMPT_SLUG,
)
from app.services.prompt_service import (
    get_prompt_by_slug,
    list_prompt_revisions,
    restore_prompt_revision,
    update_prompt,
)
from scripts.jenny_honing._constants import CHANGED_BY
from scripts.jenny_honing._models import JennyMutableState


async def _prompt_state(db, prompt_slug: str) -> tuple[str | None, str | None]:
    prompt = await get_prompt_by_slug(db, prompt_slug)
    revisions = await list_prompt_revisions(db, prompt_slug, limit=1)
    return (
        prompt.content if prompt is not None else None,
        revisions[0].id if revisions else None,
    )


async def _capture_jenny_mutable_state(agent_slug: str) -> JennyMutableState:
    async with async_session() as db:
        heartbeat_instructions = await get_persona_heartbeat_instructions(db) or ""
        revisions = await list_prompt_revisions(db, PERSONA_HEARTBEAT_INSTRUCTIONS_PROMPT_SLUG, limit=1)
        heartbeat_revision_id = revisions[0].id if revisions else None
        agent_service = get_agent_service()
        agent = await agent_service.get_by_slug(db, agent_slug)
        if agent is None:
            raise RuntimeError(f"Agent '{agent_slug}' not found")
        supervisor = await agent_service.get_by_slug(db, "supervisor")
        completion_review_prompt, completion_review_prompt_revision_id = await _prompt_state(
            db,
            COMPLETION_REVIEW_PROMPT_SLUG
        )
        completion_review_rules, completion_review_rules_revision_id = await _prompt_state(
            db,
            COMPLETION_REVIEW_RULES_PROMPT_SLUG
        )
        return JennyMutableState(
            heartbeat_instructions=heartbeat_instructions,
            heartbeat_revision_id=heartbeat_revision_id,
            primary_model_id=agent.primary_model_id,
            fallback_models=list(agent.fallback_models or []),
            escalation_model_id=agent.escalation_model_id,
            temperature=float(agent.temperature),
            thinking_level=agent.thinking_level,
            supervisor_primary_model_id=(
                supervisor.primary_model_id if supervisor is not None else None
            ),
            supervisor_fallback_models=list(supervisor.fallback_models or []) if supervisor is not None else [],
            supervisor_escalation_model_id=(
                supervisor.escalation_model_id if supervisor is not None else None
            ),
            supervisor_temperature=(
                float(supervisor.temperature) if supervisor is not None else None
            ),
            supervisor_thinking_level=(
                supervisor.thinking_level if supervisor is not None else None
            ),
            completion_review_prompt=completion_review_prompt,
            completion_review_prompt_revision_id=completion_review_prompt_revision_id,
            completion_review_rules=completion_review_rules,
            completion_review_rules_revision_id=completion_review_rules_revision_id,
        )


async def _restore_prompt_content(
    *,
    prompt_slug: str,
    revision_id: str | None,
    content: str | None,
    reason: str,
) -> None:
    async with async_session() as db:
        if revision_id:
            await restore_prompt_revision(
                db,
                prompt_slug,
                revision_id,
                changed_by=CHANGED_BY,
                change_reason=reason,
            )
            return
        if content is None:
            return
        await update_prompt(
            db,
            prompt_slug,
            changed_by=CHANGED_BY,
            change_reason=reason,
            content=content,
        )


async def _restore_jenny_mutable_state(
    agent_slug: str,
    state: JennyMutableState,
    *,
    reason: str,
) -> None:
    await _restore_prompt_content(
        prompt_slug=PERSONA_HEARTBEAT_INSTRUCTIONS_PROMPT_SLUG,
        revision_id=state.heartbeat_revision_id,
        content=state.heartbeat_instructions,
        reason=reason,
    )
    await _restore_prompt_content(
        prompt_slug=COMPLETION_REVIEW_PROMPT_SLUG,
        revision_id=state.completion_review_prompt_revision_id,
        content=state.completion_review_prompt,
        reason=reason,
    )
    await _restore_prompt_content(
        prompt_slug=COMPLETION_REVIEW_RULES_PROMPT_SLUG,
        revision_id=state.completion_review_rules_revision_id,
        content=state.completion_review_rules,
        reason=reason,
    )
    async with async_session() as db:
        agent_service = get_agent_service()
        agent = await agent_service.get_by_slug(db, agent_slug)
        if agent is None:
            raise RuntimeError(f"Agent '{agent_slug}' not found for restore")
        await agent_service.update(
            db,
            agent.id,
            primary_model_id=state.primary_model_id,
            fallback_models=list(state.fallback_models),
            escalation_model_id=state.escalation_model_id,
            temperature=state.temperature,
            thinking_level=state.thinking_level,
            changed_by=CHANGED_BY,
            change_reason=reason,
        )
        supervisor = await agent_service.get_by_slug(db, "supervisor")
        if supervisor is not None and state.supervisor_primary_model_id is not None:
            await agent_service.update(
                db,
                supervisor.id,
                primary_model_id=state.supervisor_primary_model_id,
                fallback_models=list(state.supervisor_fallback_models),
                escalation_model_id=state.supervisor_escalation_model_id,
                temperature=state.supervisor_temperature,
                thinking_level=state.supervisor_thinking_level,
                changed_by=CHANGED_BY,
                change_reason=reason,
            )
