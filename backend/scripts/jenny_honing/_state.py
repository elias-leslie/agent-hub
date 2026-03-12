"""Jenny mutable state capture and restore."""
from __future__ import annotations

from app.db import async_session
from app.services.agent_service import get_agent_service
from app.services.persona_instruction_service import (
    get_persona_heartbeat_instructions,
    set_persona_heartbeat_instructions,
)
from app.services.prompt_service import list_prompt_revisions, restore_prompt_revision
from scripts.jenny_honing._constants import CHANGED_BY
from scripts.jenny_honing._models import JennyMutableState


async def _capture_jenny_mutable_state(agent_slug: str) -> JennyMutableState:
    async with async_session() as db:
        heartbeat_instructions = await get_persona_heartbeat_instructions(db) or ""
        revisions = await list_prompt_revisions(db, "persona-heartbeat-instructions", limit=1)
        heartbeat_revision_id = revisions[0].id if revisions else None
        agent_service = get_agent_service()
        agent = await agent_service.get_by_slug(db, agent_slug)
        if agent is None:
            raise RuntimeError(f"Agent '{agent_slug}' not found")
        return JennyMutableState(
            heartbeat_instructions=heartbeat_instructions,
            heartbeat_revision_id=heartbeat_revision_id,
            primary_model_id=agent.primary_model_id,
            fallback_models=list(agent.fallback_models or []),
            escalation_model_id=agent.escalation_model_id,
            temperature=float(agent.temperature),
            thinking_level=agent.thinking_level,
        )


async def _restore_jenny_mutable_state(
    agent_slug: str,
    state: JennyMutableState,
    *,
    reason: str,
) -> None:
    async with async_session() as db:
        if state.heartbeat_revision_id:
            await restore_prompt_revision(
                db,
                "persona-heartbeat-instructions",
                state.heartbeat_revision_id,
                changed_by=CHANGED_BY,
                change_reason=reason,
            )
        else:
            await set_persona_heartbeat_instructions(
                db,
                state.heartbeat_instructions,
                changed_by=CHANGED_BY,
                change_reason=reason,
            )
            await db.commit()

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
