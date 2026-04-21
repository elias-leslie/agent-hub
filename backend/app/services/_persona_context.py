"""Persona context-building helpers — prompt injection for agents."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.persona import Persona
from app.services._persona_crud import get_persona_for_agent
from app.services.persona_document_prompt_service import (
    get_persona_personality_document,
    get_persona_user_context_document,
)
from app.services.persona_documents import render_user_profile
from app.services.persona_prompt_service import (
    get_persona_evolution_guidelines,
    get_persona_focus_harness,
    get_persona_onboarding_pending_approval,
    render_persona_onboarding_bootstrap,
    render_persona_onboarding_continuation,
)

logger = logging.getLogger(__name__)


async def _build_onboarding_section(
    persona: Persona,
    *,
    user_context_text: str | None,
) -> str | None:
    """Return the onboarding XML section for the current phase, or None."""
    phase = persona.onboarding_phase
    if phase == "not_started":
        text = await render_persona_onboarding_bootstrap(
            persona.name,
            has_prior_context=user_context_text is not None,
        )
        return f"<onboarding>\n{text}\n</onboarding>"
    if phase == "in_progress":
        if user_context_text:
            text = await render_persona_onboarding_continuation(persona.name)
        else:
            text = await render_persona_onboarding_bootstrap(
                persona.name,
                has_prior_context=False,
            )
        return f"<onboarding>\n{text}\n</onboarding>"
    if phase == "pending_approval":
        pending_approval = await get_persona_onboarding_pending_approval()
        return f"<onboarding>\n{pending_approval}\n</onboarding>"
    return None  # phase == "complete"


async def _handle_onboarding_phase_transition(
    db: AsyncSession,
    persona: Persona,
    phase: str,
    *,
    user_context_text: str | None,
) -> None:
    """Advance onboarding phase from not_started to in_progress."""
    if phase == "not_started":
        persona.onboarding_phase = "in_progress"
        await db.flush()
        logger.info("Persona onboarding bootstrap injected; phase → in_progress")
    elif phase == "in_progress" and not user_context_text:
        logger.info("Persona onboarding re-bootstrapped (no prior context)")


def _build_persona_sections(
    persona: Persona,
    *,
    personality_text: str | None,
    user_context_text: str | None,
    include_user_context_notes: bool = True,
) -> list[str]:
    """Assemble the static persona XML sections."""
    sections: list[str] = [f'<identity name="{persona.name}" />']
    if persona.greeting:
        sections.append(f"<greeting>\n{persona.greeting}\n</greeting>")
    if personality_text:
        sections.append(f"<personality>\n{personality_text}\n</personality>")
    rendered_profile = render_user_profile(persona.user_profile)
    if rendered_profile:
        sections.append(f"<user_profile>\n{rendered_profile}\n</user_profile>")
    if include_user_context_notes and user_context_text:
        sections.append(f"<user_context_notes>\n{user_context_text}\n</user_context_notes>")
    return sections


async def get_persona_context_for_agent(
    db: AsyncSession,
    agent_id: int,
    task_type: str | None = None,
    *,
    mutate_phase: bool = True,
) -> str | None:
    """Build the full persona context block for prompt injection.

    Returns the formatted context string, or None if no persona exists.

    Args:
        task_type: When "heartbeat", includes heartbeat_instructions section.
            Other values (or None) omit it to save tokens in chat sessions.
    """
    persona = await get_persona_for_agent(db, agent_id)
    if not persona:
        return None

    sections: list[str] = []
    phase = persona.onboarding_phase
    personality_text = await get_persona_personality_document(db)
    user_context_text = await get_persona_user_context_document(db)

    onboarding_section = await _build_onboarding_section(
        persona,
        user_context_text=user_context_text,
    )
    if onboarding_section:
        sections.append(onboarding_section)
        if mutate_phase:
            await _handle_onboarding_phase_transition(
                db,
                persona,
                phase,
                user_context_text=user_context_text,
            )

    if task_type == "heartbeat":
        from app.services.persona_instruction_service import (
            get_persona_heartbeat_instructions,
        )

        heartbeat_instructions = await get_persona_heartbeat_instructions(db)
    else:
        heartbeat_instructions = None

    sections.extend(
        _build_persona_sections(
            persona,
            personality_text=personality_text,
            user_context_text=user_context_text,
            include_user_context_notes=task_type not in {"heartbeat", "wake"},
        )
    )
    if task_type in {"heartbeat", "wake"}:
        focus_harness = await get_persona_focus_harness()
        sections.append(f"<focus_harness>\n{focus_harness}\n</focus_harness>")
    if heartbeat_instructions:
        sections.append(
            f"<heartbeat_instructions>\n{heartbeat_instructions}\n</heartbeat_instructions>"
        )

    if phase == "complete" and task_type != "heartbeat":
        evolution_guidelines = await get_persona_evolution_guidelines()
        sections.append(
            f"<evolution_guidelines>\n{evolution_guidelines}\n</evolution_guidelines>"
        )

    return "\n\n".join(sections)
