"""Prompt management service with CRUD and composition logic."""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.prompt import AgentPrompt, Prompt, PromptRevision

logger = logging.getLogger(__name__)


def _prompt_content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


async def record_prompt_revision(
    db: AsyncSession,
    prompt: Prompt,
    *,
    action: str,
    changed_by: str | None = None,
    change_reason: str | None = None,
) -> PromptRevision:
    """Persist an immutable revision snapshot for one prompt state."""
    revision = PromptRevision(
        prompt_id=prompt.id,
        prompt_slug=prompt.slug,
        prompt_name=prompt.name,
        action=action,
        content=prompt.content,
        description=prompt.description,
        is_global=prompt.is_global,
        enabled=prompt.enabled,
        exclude_agents=list(prompt.exclude_agents or []),
        owner_agent_id=prompt.owner_agent_id,
        prompt_type=prompt.prompt_type,
        deletion_locked=prompt.deletion_locked,
        content_hash=_prompt_content_hash(prompt.content),
        changed_by=changed_by,
        change_reason=change_reason,
    )
    db.add(revision)
    await db.flush()
    return revision


async def get_all_prompts(
    db: AsyncSession,
    *,
    is_global: bool | None = None,
    enabled_only: bool = False,
) -> list[Prompt]:
    """List prompts with optional global filter."""
    stmt = select(Prompt).options(selectinload(Prompt.owner_agent)).order_by(Prompt.slug)
    if is_global is not None:
        stmt = stmt.where(Prompt.is_global == is_global)
    if enabled_only:
        stmt = stmt.where(Prompt.enabled == True)  # noqa: E712
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_prompt_by_slug(db: AsyncSession, slug: str) -> Prompt | None:
    """Get a single prompt by slug."""
    result = await db.execute(
        select(Prompt)
        .options(selectinload(Prompt.owner_agent))
        .where(Prompt.slug == slug)
    )
    return result.scalar_one_or_none()


async def create_prompt(
    db: AsyncSession,
    *,
    slug: str,
    name: str,
    content: str,
    description: str | None = None,
    is_global: bool = False,
    enabled: bool = True,
    exclude_agents: list[str] | None = None,
    owner_agent_id: int | None = None,
    prompt_type: str = "standard",
    deletion_locked: bool = False,
    changed_by: str | None = None,
    change_reason: str | None = None,
) -> Prompt:
    """Create a new prompt."""
    prompt = Prompt(
        slug=slug,
        name=name,
        content=content,
        description=description,
        is_global=is_global,
        enabled=enabled,
        exclude_agents=exclude_agents or [],
        owner_agent_id=owner_agent_id,
        prompt_type=prompt_type,
        deletion_locked=deletion_locked,
    )
    db.add(prompt)
    await db.flush()
    await record_prompt_revision(
        db,
        prompt,
        action="create",
        changed_by=changed_by,
        change_reason=change_reason or "Prompt created",
    )
    await db.commit()
    await db.refresh(prompt)
    logger.info("Created prompt: %s (global=%s)", slug, is_global)
    return prompt


async def update_prompt(
    db: AsyncSession,
    slug: str,
    changed_by: str | None = None,
    change_reason: str | None = None,
    **kwargs: Any,
) -> Prompt | None:
    """Update an existing prompt by slug. Only provided kwargs are updated."""
    prompt = await get_prompt_by_slug(db, slug)
    if not prompt:
        return None

    allowed_fields = {
        "name",
        "content",
        "description",
        "is_global",
        "enabled",
        "slug",
        "exclude_agents",
    }
    for key, value in kwargs.items():
        if key in allowed_fields and value is not None:
            setattr(prompt, key, value)

    await db.flush()
    await record_prompt_revision(
        db,
        prompt,
        action="update",
        changed_by=changed_by,
        change_reason=change_reason or "Prompt updated",
    )
    await db.commit()
    await db.refresh(prompt)
    logger.info("Updated prompt: %s", slug)
    return prompt


async def delete_prompt(db: AsyncSession, slug: str) -> bool:
    """Delete a prompt by slug. Cascades to agent_prompts."""
    prompt = await get_prompt_by_slug(db, slug)
    if not prompt:
        return False
    if prompt.deletion_locked:
        raise ValueError(f"Prompt '{slug}' is locked and cannot be deleted")

    await record_prompt_revision(
        db,
        prompt,
        action="delete",
        changed_by="api",
        change_reason="Prompt deleted",
    )
    await db.delete(prompt)
    await db.commit()
    logger.info("Deleted prompt: %s", slug)
    return True


async def list_prompt_revisions(
    db: AsyncSession,
    slug: str,
    *,
    limit: int = 20,
) -> list[PromptRevision]:
    """List recent immutable revisions for one prompt slug."""
    stmt = (
        select(PromptRevision)
        .where(PromptRevision.prompt_slug == slug)
        .order_by(PromptRevision.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_prompt_revision(
    db: AsyncSession,
    slug: str,
    revision_id: str,
) -> PromptRevision | None:
    """Fetch a specific revision for one prompt slug."""
    stmt = select(PromptRevision).where(
        PromptRevision.prompt_slug == slug,
        PromptRevision.id == revision_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def restore_prompt_revision(
    db: AsyncSession,
    slug: str,
    revision_id: str,
    *,
    changed_by: str | None = None,
    change_reason: str | None = None,
) -> Prompt | None:
    """Restore a prompt to a previous revision and record the restore."""
    prompt = await get_prompt_by_slug(db, slug)
    revision = await get_prompt_revision(db, slug, revision_id)
    if not prompt or not revision:
        return None

    prompt.name = revision.prompt_name
    prompt.content = revision.content
    prompt.description = revision.description
    prompt.is_global = revision.is_global
    prompt.enabled = revision.enabled
    prompt.exclude_agents = list(revision.exclude_agents or [])

    await db.flush()
    await record_prompt_revision(
        db,
        prompt,
        action="restore",
        changed_by=changed_by,
        change_reason=change_reason or f"Restored revision {revision_id}",
    )
    await db.commit()
    await db.refresh(prompt)
    return prompt


async def get_agent_prompts(
    db: AsyncSession,
    agent_id: int,
    *,
    include_roles: list[str] | None = None,
) -> list[AgentPrompt]:
    """Get all prompts assigned to an agent, ordered by priority ASC.

    Args:
        db: Database session
        agent_id: Agent ID
        include_roles: When provided, only return assignments with matching roles.
            When None (default), returns all assignments.
    """
    stmt = (
        select(AgentPrompt)
        .options(selectinload(AgentPrompt.prompt).selectinload(Prompt.owner_agent))
        .where(AgentPrompt.agent_id == agent_id)
        .order_by(AgentPrompt.priority.asc())
    )
    if include_roles is not None:
        stmt = stmt.where(AgentPrompt.role.in_(include_roles))
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
    *,
    include_roles: list[str] | None = None,
    agent_slug: str | None = None,
) -> str:
    """Compose global prompts + agent's role-assigned prompts into a single block.

    Composition order:
    1. Global prompts (is_global=true, ordered by slug) — skipping any that exclude this agent
    2. Agent's assigned prompts (ordered by priority ASC)

    Args:
        db: Database session
        agent_id: Agent ID
        include_roles: When provided, only include agent assignments with matching roles.
            When None (default), includes all assignments (backwards compatible).
        agent_slug: When provided, skip global prompts whose exclude_agents list
            contains this slug.
    """
    sections: list[str] = []

    global_prompts = await get_all_prompts(db, is_global=True)
    for p in global_prompts:
        if not p.enabled:
            continue
        if agent_slug and p.exclude_agents and agent_slug in p.exclude_agents:
            logger.debug("Skipping global prompt '%s' (excluded for agent '%s')", p.slug, agent_slug)
            continue
        sections.append(p.content)

    agent_assignments = await get_agent_prompts(db, agent_id, include_roles=include_roles)
    for ap in agent_assignments:
        if not ap.prompt.enabled:
            continue
        sections.append(ap.prompt.content)

    return "\n\n".join(sections)


async def get_prompt_content(slug: str, default: str) -> str:
    """Fetch prompt content by slug from DB, falling back to default.

    Opens its own DB session so callers (summary_generator, learning_extractor,
    mcp_server) don't need to manage sessions.

    Args:
        slug: Prompt slug to look up
        default: Fallback content if prompt not found in DB

    Returns:
        Prompt content from DB, or the default string
    """
    try:
        from app.db import async_session

        async with async_session() as db:
            prompt = await get_prompt_by_slug(db, slug)
            if prompt:
                return prompt.content
    except Exception as e:
        logger.debug("Prompt lookup for '%s' failed (using default): %s", slug, e)
    return default


async def require_prompt_content(slug: str) -> str:
    """Fetch prompt content by slug or raise when the DB prompt is missing/empty."""
    from app.db import async_session

    async with async_session() as db:
        prompt = await get_prompt_by_slug(db, slug)
        if not prompt or not prompt.content.strip():
            raise RuntimeError(f"Required prompt '{slug}' is missing or empty")
        if not prompt.enabled:
            raise RuntimeError(f"Required prompt '{slug}' is disabled")
        return prompt.content
