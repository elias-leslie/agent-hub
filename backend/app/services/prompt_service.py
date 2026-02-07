"""Prompt management service with CRUD and composition logic."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.prompt import AgentPrompt, Prompt

logger = logging.getLogger(__name__)


async def get_all_prompts(
    db: AsyncSession,
    *,
    is_global: bool | None = None,
) -> list[Prompt]:
    """List prompts with optional global filter."""
    stmt = select(Prompt).order_by(Prompt.slug)
    if is_global is not None:
        stmt = stmt.where(Prompt.is_global == is_global)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_prompt_by_slug(db: AsyncSession, slug: str) -> Prompt | None:
    """Get a single prompt by slug."""
    result = await db.execute(select(Prompt).where(Prompt.slug == slug))
    return result.scalar_one_or_none()


async def create_prompt(
    db: AsyncSession,
    *,
    slug: str,
    name: str,
    content: str,
    description: str | None = None,
    is_global: bool = False,
) -> Prompt:
    """Create a new prompt."""
    prompt = Prompt(
        slug=slug,
        name=name,
        content=content,
        description=description,
        is_global=is_global,
    )
    db.add(prompt)
    await db.commit()
    await db.refresh(prompt)
    logger.info("Created prompt: %s (global=%s)", slug, is_global)
    return prompt


async def update_prompt(
    db: AsyncSession,
    slug: str,
    **kwargs: Any,
) -> Prompt | None:
    """Update an existing prompt by slug. Only provided kwargs are updated."""
    prompt = await get_prompt_by_slug(db, slug)
    if not prompt:
        return None

    allowed_fields = {"name", "content", "description", "is_global", "slug"}
    for key, value in kwargs.items():
        if key in allowed_fields and value is not None:
            setattr(prompt, key, value)

    await db.commit()
    await db.refresh(prompt)
    logger.info("Updated prompt: %s", slug)
    return prompt


async def delete_prompt(db: AsyncSession, slug: str) -> bool:
    """Delete a prompt by slug. Cascades to agent_prompts."""
    prompt = await get_prompt_by_slug(db, slug)
    if not prompt:
        return False

    await db.delete(prompt)
    await db.commit()
    logger.info("Deleted prompt: %s", slug)
    return True


async def get_agent_prompts(
    db: AsyncSession,
    agent_id: int,
) -> list[AgentPrompt]:
    """Get all prompts assigned to an agent, ordered by priority ASC."""
    stmt = (
        select(AgentPrompt)
        .options(selectinload(AgentPrompt.prompt))
        .where(AgentPrompt.agent_id == agent_id)
        .order_by(AgentPrompt.priority.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def assign_prompt(
    db: AsyncSession,
    *,
    agent_id: int,
    prompt_id: int,
    role: str,
    priority: int = 0,
) -> AgentPrompt:
    """Assign a prompt to an agent with a role and priority."""
    assignment = AgentPrompt(
        agent_id=agent_id,
        prompt_id=prompt_id,
        role=role,
        priority=priority,
    )
    db.add(assignment)
    await db.commit()
    await db.refresh(assignment)
    logger.info("Assigned prompt %d to agent %d (role=%s)", prompt_id, agent_id, role)
    return assignment


async def remove_assignment(
    db: AsyncSession,
    agent_id: int,
    prompt_id: int,
) -> bool:
    """Remove a prompt assignment from an agent."""
    stmt = select(AgentPrompt).where(
        AgentPrompt.agent_id == agent_id,
        AgentPrompt.prompt_id == prompt_id,
    )
    result = await db.execute(stmt)
    assignment = result.scalar_one_or_none()
    if not assignment:
        return False
    await db.delete(assignment)
    await db.commit()
    return True


async def update_assignment(
    db: AsyncSession,
    agent_id: int,
    prompt_id: int,
    *,
    role: str | None = None,
    priority: int | None = None,
) -> AgentPrompt | None:
    """Update role/priority on an existing assignment."""
    stmt = select(AgentPrompt).where(
        AgentPrompt.agent_id == agent_id,
        AgentPrompt.prompt_id == prompt_id,
    )
    result = await db.execute(stmt)
    assignment = result.scalar_one_or_none()
    if not assignment:
        return None

    if role is not None:
        assignment.role = role
    if priority is not None:
        assignment.priority = priority

    await db.commit()
    await db.refresh(assignment)
    return assignment


async def get_distinct_roles(db: AsyncSession) -> list[str]:
    """Get all distinct role strings from agent_prompts."""
    result = await db.execute(
        select(AgentPrompt.role).distinct().order_by(AgentPrompt.role)
    )
    return [row[0] for row in result.all()]


async def build_prompt_context(
    db: AsyncSession,
    agent_id: int,
) -> str:
    """Compose global prompts + agent's role-assigned prompts into a single block.

    Composition order:
    1. Global prompts (is_global=true, ordered by slug)
    2. Agent's assigned prompts (ordered by priority ASC)
    """
    sections: list[str] = []

    global_prompts = await get_all_prompts(db, is_global=True)
    for p in global_prompts:
        sections.append(p.content)

    agent_assignments = await get_agent_prompts(db, agent_id)
    for ap in agent_assignments:
        sections.append(ap.prompt.content)

    return "\n\n".join(sections)
