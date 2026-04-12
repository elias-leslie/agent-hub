"""CRUD helper functions for agents."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Agent, AgentVersion


async def get_agent_by_id(db: AsyncSession, agent_id: int) -> Agent | None:
    """Get agent model by ID."""
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    return result.scalar_one_or_none()


async def get_agent_by_slug(db: AsyncSession, slug: str, active_only: bool = True) -> Agent | None:
    """Get agent model by slug."""
    query = select(Agent).where(Agent.slug == slug)
    if active_only:
        query = query.where(Agent.is_active == True)  # noqa: E712
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def list_agents_query(
    db: AsyncSession,
    *,
    active_only: bool = True,
    coding_only: bool | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Agent]:
    """Query agents with filters."""
    query = select(Agent)

    if active_only:
        query = query.where(Agent.is_active == True)  # noqa: E712

    if coding_only is True:
        query = query.where(Agent.is_coding_agent == True)  # noqa: E712
    elif coding_only is False:
        query = query.where(Agent.is_coding_agent == False)  # noqa: E712

    query = query.order_by(Agent.slug).limit(limit).offset(offset)

    result = await db.execute(query)
    return list(result.scalars().all())


def create_agent_model(
    slug: str,
    name: str,
    system_prompt: str,
    primary_model_id: str,
    description: str | None = None,
    fallback_models: list[str] | None = None,
    escalation_model_id: str | None = None,
    strategies: dict[str, Any] | None = None,
    temperature: float = 0.7,
    thinking_level: str | None = None,
    verbosity_level: str | None = None,
    is_active: bool = True,
    is_coding_agent: bool = False,
    memory_config: dict[str, Any] | None = None,
    max_concurrency: int | None = None,
    max_subagent_concurrency: int | None = None,
    daily_token_budget: int | None = None,
    hourly_request_limit: int | None = None,
    timeout_seconds: float | None = None,
) -> Agent:
    """Create agent model instance."""
    return Agent(
        slug=slug,
        name=name,
        description=description,
        system_prompt=system_prompt,
        primary_model_id=primary_model_id,
        fallback_models=fallback_models or [],
        escalation_model_id=escalation_model_id,
        strategies=strategies or {},
        temperature=temperature,
        thinking_level=thinking_level,
        verbosity_level=verbosity_level,
        is_active=is_active,
        is_coding_agent=is_coding_agent,
        memory_config=memory_config,
        max_concurrency=max_concurrency,
        max_subagent_concurrency=max_subagent_concurrency,
        daily_token_budget=daily_token_budget,
        hourly_request_limit=hourly_request_limit,
        timeout_seconds=timeout_seconds,
        version=1,
    )


def apply_agent_updates(agent: Agent, **updates: Any) -> None:
    """Apply updates to agent model."""
    for field, value in updates.items():
        if value is not None:
            setattr(agent, field, value)


async def create_version_record(
    db: AsyncSession,
    agent_id: int,
    version: int,
    config_snapshot: dict[str, Any],
    changed_by: str | None,
    change_reason: str,
) -> None:
    """Create an agent version record."""
    version_record = AgentVersion(
        agent_id=agent_id,
        version=version,
        config_snapshot=config_snapshot,
        changed_by=changed_by,
        change_reason=change_reason,
    )
    db.add(version_record)
    await db.commit()


async def get_version_history(
    db: AsyncSession,
    agent_id: int,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Get version history for an agent."""
    result = await db.execute(
        select(AgentVersion)
        .where(AgentVersion.agent_id == agent_id)
        .order_by(AgentVersion.version.desc())
        .limit(limit)
    )
    versions = result.scalars().all()

    return [
        {
            "version": v.version,
            "config_snapshot": v.config_snapshot,
            "changed_by": v.changed_by,
            "change_reason": v.change_reason,
            "created_at": v.created_at.isoformat(),
        }
        for v in versions
    ]
