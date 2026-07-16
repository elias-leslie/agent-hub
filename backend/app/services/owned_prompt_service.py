"""Helpers for agent-owned prompt records."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.prompt import AgentPrompt, Prompt
from app.services.prompt_catalog import (
    PERSONA_HEARTBEAT_INSTRUCTIONS_PROMPT_SLUG,
    build_agent_system_prompt_slug,
)
from app.services.prompt_service import get_prompt_by_slug, record_prompt_revision

STANDARD_PROMPT_TYPE = "standard"
AGENT_SYSTEM_PROMPT_TYPE = "agent_system"
GLOBAL_MANDATE_PROMPT_TYPE = "global_mandate"
GLOBAL_GUARDRAIL_PROMPT_TYPE = "global_guardrail"
PERSONA_HEARTBEAT_INSTRUCTIONS_PROMPT_TYPE = "persona_heartbeat_instructions"


async def _get_assignment(
    db: AsyncSession,
    *,
    agent_id: int,
    prompt_id: int,
) -> AgentPrompt | None:
    result = await db.execute(
        select(AgentPrompt).where(
            AgentPrompt.agent_id == agent_id,
            AgentPrompt.prompt_id == prompt_id,
        )
    )
    return result.scalar_one_or_none()


async def _ensure_assignment(
    db: AsyncSession,
    *,
    agent_id: int,
    prompt_id: int,
    role: str,
    priority: int,
) -> AgentPrompt:
    assignment = await _get_assignment(db, agent_id=agent_id, prompt_id=prompt_id)
    if assignment is None:
        assignment = AgentPrompt(
            agent_id=agent_id,
            prompt_id=prompt_id,
            role=role,
            priority=priority,
        )
        db.add(assignment)
        await db.flush()
        return assignment

    assignment.role = role
    assignment.priority = priority
    await db.flush()
    return assignment


async def get_owned_prompt(
    db: AsyncSession,
    *,
    agent_id: int,
    prompt_type: str,
) -> Prompt | None:
    result = await db.execute(
        select(Prompt).where(
            Prompt.owner_agent_id == agent_id,
            Prompt.prompt_type == prompt_type,
        )
    )
    return result.scalar_one_or_none()


async def ensure_owned_prompt(
    db: AsyncSession,
    *,
    agent: Agent,
    slug: str,
    name: str,
    content: str,
    description: str | None,
    prompt_type: str,
    role: str,
    priority: int,
    deletion_locked: bool = False,
    enabled: bool = True,
    changed_by: str | None = None,
    change_reason: str | None = None,
) -> Prompt:
    prompt = await get_prompt_by_slug(db, slug)
    action = None
    normalized_content = content.strip()
    if prompt is None:
        prompt = Prompt(
            slug=slug,
            name=name,
            content=normalized_content,
            description=description,
            is_global=False,
            enabled=enabled,
            exclude_agents=[],
            owner_agent_id=agent.id,
            prompt_type=prompt_type,
            deletion_locked=deletion_locked,
        )
        db.add(prompt)
        await db.flush()
        action = "create"
    else:
        changed = False
        updates: dict[str, Any] = {
            "name": name,
            "content": normalized_content,
            "description": description,
            "is_global": False,
            "enabled": enabled,
            "exclude_agents": [],
            "owner_agent_id": agent.id,
            "prompt_type": prompt_type,
            "deletion_locked": deletion_locked,
        }
        for field, value in updates.items():
            if getattr(prompt, field) != value:
                setattr(prompt, field, value)
                changed = True
        if changed:
            await db.flush()
            action = "update"

    await _ensure_assignment(
        db,
        agent_id=agent.id,
        prompt_id=prompt.id,
        role=role,
        priority=priority,
    )

    if action is not None:
        await record_prompt_revision(
            db,
            prompt,
            action=action,
            changed_by=changed_by,
            change_reason=change_reason or f"Synced owned prompt '{slug}'",
        )

    return prompt


async def sync_agent_system_prompt(
    db: AsyncSession,
    *,
    agent: Agent,
    system_prompt: str,
    changed_by: str | None = None,
    change_reason: str | None = None,
) -> Prompt:
    return await ensure_owned_prompt(
        db,
        agent=agent,
        slug=build_agent_system_prompt_slug(agent.slug),
        name=f"{agent.name} System Prompt",
        content=system_prompt,
        description=f"Primary system prompt for {agent.name}.",
        prompt_type=AGENT_SYSTEM_PROMPT_TYPE,
        role="system",
        priority=0,
        deletion_locked=True,
        changed_by=changed_by,
        change_reason=change_reason,
    )


async def sync_persona_instruction_prompts(
    db: AsyncSession,
    *,
    agent: Agent,
    heartbeat_instructions: str,
    changed_by: str | None = None,
    change_reason: str | None = None,
) -> None:
    await ensure_owned_prompt(
        db,
        agent=agent,
        slug=PERSONA_HEARTBEAT_INSTRUCTIONS_PROMPT_SLUG,
        name="Persona Heartbeat Instructions",
        content=heartbeat_instructions,
        description="Persona-specific mutable guidance for heartbeat runs.",
        prompt_type=PERSONA_HEARTBEAT_INSTRUCTIONS_PROMPT_TYPE,
        role="heartbeat-instructions",
        priority=40,
        changed_by=changed_by,
        change_reason=change_reason,
    )


__all__ = [
    "AGENT_SYSTEM_PROMPT_TYPE",
    "GLOBAL_GUARDRAIL_PROMPT_TYPE",
    "GLOBAL_MANDATE_PROMPT_TYPE",
    "PERSONA_HEARTBEAT_INSTRUCTIONS_PROMPT_TYPE",
    "STANDARD_PROMPT_TYPE",
    "ensure_owned_prompt",
    "get_owned_prompt",
    "sync_agent_system_prompt",
    "sync_persona_instruction_prompts",
]
