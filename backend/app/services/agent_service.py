"""Agent service with CRUD operations and Redis caching.

Provides:
- CRUD operations for agents
- Redis caching for frequently accessed agents
- Version tracking for audit history
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services.agent_cache import AgentCache
from app.services.agent_crud import (
    apply_agent_updates,
    create_agent_model,
    create_version_record,
    get_agent_by_id,
    get_agent_by_slug,
    list_agents_query,
)
from app.services.agent_crud import (
    get_version_history as get_version_history_crud,
)
from app.services.agent_dto import AgentDTO

logger = logging.getLogger(__name__)

# Export public API
__all__ = ["AgentDTO", "AgentService", "get_agent_service"]


class AgentService:
    """Service for agent CRUD operations with Redis caching."""

    def __init__(self, redis_url: str | None = None):
        """Initialize agent service."""
        url = redis_url or settings.agent_hub_redis_url
        self._cache = AgentCache(url)

    async def get_by_slug(self, db: AsyncSession, slug: str) -> AgentDTO | None:
        """Get agent by slug with caching."""
        cached = await self._cache.get(slug)
        if cached:
            return cached

        agent = await get_agent_by_slug(db, slug, active_only=True)

        if agent:
            dto = AgentDTO.from_model(agent)
            await self._cache.set(dto)
            return dto

        return None

    async def get_by_id(self, db: AsyncSession, agent_id: int) -> AgentDTO | None:
        """Get agent by ID."""
        agent = await get_agent_by_id(db, agent_id)
        return AgentDTO.from_model(agent) if agent else None

    async def list_agents(
        self,
        db: AsyncSession,
        *,
        active_only: bool = True,
        coding_only: bool | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AgentDTO]:
        """List agents with filtering."""
        agents = await list_agents_query(
            db, active_only=active_only, coding_only=coding_only, limit=limit, offset=offset
        )
        return [AgentDTO.from_model(a) for a in agents]

    async def create(
        self,
        db: AsyncSession,
        *,
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
        tool_permissions: dict[str, Any] | None = None,
        memory_config: dict[str, Any] | None = None,
        max_concurrency: int | None = None,
        max_subagent_concurrency: int | None = None,
        daily_token_budget: int | None = None,
        hourly_request_limit: int | None = None,
        timeout_seconds: float | None = None,
        changed_by: str | None = None,
    ) -> AgentDTO:
        """Create a new agent."""
        agent = create_agent_model(
            slug=slug,
            name=name,
            description=description,
            system_prompt=system_prompt,
            primary_model_id=primary_model_id,
            fallback_models=fallback_models,
            escalation_model_id=escalation_model_id,
            strategies=strategies,
            temperature=temperature,
            thinking_level=thinking_level,
            verbosity_level=verbosity_level,
            is_active=is_active,
            is_coding_agent=is_coding_agent,
            tool_permissions=tool_permissions,
            memory_config=memory_config,
            max_concurrency=max_concurrency,
            max_subagent_concurrency=max_subagent_concurrency,
            daily_token_budget=daily_token_budget,
            hourly_request_limit=hourly_request_limit,
            timeout_seconds=timeout_seconds,
        )
        db.add(agent)
        await db.commit()
        await db.refresh(agent)
        dto = AgentDTO.from_model(agent)
        await self._finalize_create(db, agent.id, dto, changed_by)
        logger.info(f"Created agent: {slug}")
        return dto

    async def _finalize_create(
        self,
        db: AsyncSession,
        agent_id: int,
        dto: AgentDTO,
        changed_by: str | None,
    ) -> None:
        """Persist initial version record and prime cache after create."""
        await create_version_record(db, agent_id, 1, dto.to_dict(), changed_by, "Initial creation")
        await self._cache.set(dto)

    async def update(
        self,
        db: AsyncSession,
        agent_id: int,
        *,
        name: str | None = None,
        description: str | None = None,
        system_prompt: str | None = None,
        primary_model_id: str | None = None,
        fallback_models: list[str] | None = None,
        escalation_model_id: str | None = None,
        strategies: dict[str, Any] | None = None,
        temperature: float | None = None,
        thinking_level: str | None = None,
        verbosity_level: str | None = None,
        is_active: bool | None = None,
        is_coding_agent: bool | None = None,
        tool_permissions: dict[str, Any] | None = None,
        memory_config: dict[str, Any] | None = None,
        max_concurrency: int | None = None,
        max_subagent_concurrency: int | None = None,
        daily_token_budget: int | None = None,
        hourly_request_limit: int | None = None,
        timeout_seconds: float | None = None,
        changed_by: str | None = None,
        change_reason: str | None = None,
    ) -> AgentDTO | None:
        """Update an agent. Uses optimistic locking via version field."""
        agent = await get_agent_by_id(db, agent_id)
        if not agent:
            return None

        old_slug = agent.slug
        apply_agent_updates(
            agent,
            name=name,
            description=description,
            system_prompt=system_prompt,
            primary_model_id=primary_model_id,
            fallback_models=fallback_models,
            escalation_model_id=escalation_model_id,
            strategies=strategies,
            temperature=temperature,
            thinking_level=thinking_level,
            verbosity_level=verbosity_level,
            is_active=is_active,
            is_coding_agent=is_coding_agent,
            tool_permissions=tool_permissions,
            memory_config=memory_config,
            max_concurrency=max_concurrency,
            max_subagent_concurrency=max_subagent_concurrency,
            daily_token_budget=daily_token_budget,
            hourly_request_limit=hourly_request_limit,
            timeout_seconds=timeout_seconds,
        )
        agent.version += 1
        await db.commit()
        await db.refresh(agent)
        dto = AgentDTO.from_model(agent)
        await self._finalize_update(db, agent, dto, old_slug, changed_by, change_reason)
        logger.info(f"Updated agent: {agent.slug} to version {agent.version}")
        return dto

    async def _finalize_update(
        self,
        db: AsyncSession,
        agent: Any,
        dto: AgentDTO,
        old_slug: str,
        changed_by: str | None,
        change_reason: str | None,
    ) -> None:
        """Persist version record and refresh cache after update."""
        await create_version_record(
            db, agent.id, agent.version, dto.to_dict(), changed_by, change_reason or "Updated"
        )
        await self._cache.invalidate(old_slug)
        await self._cache.set(dto)

    async def delete(
        self,
        db: AsyncSession,
        agent_id: int,
        *,
        hard_delete: bool = False,
    ) -> bool:
        """Delete or deactivate an agent."""
        agent = await get_agent_by_id(db, agent_id)
        if not agent:
            return False

        slug = agent.slug

        if hard_delete:
            await db.delete(agent)
        else:
            agent.is_active = False

        await db.commit()
        await self._cache.invalidate(slug)

        logger.info(f"{'Deleted' if hard_delete else 'Deactivated'} agent: {slug}")
        return True

    async def get_version_history(
        self,
        db: AsyncSession,
        agent_id: int,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Get version history for an agent."""
        return await get_version_history_crud(db, agent_id, limit=limit)

    async def close(self) -> None:
        """Close Redis connection."""
        await self._cache.close()


# Singleton instance
_agent_service: AgentService | None = None


def get_agent_service() -> AgentService:
    """Get the singleton agent service instance."""
    global _agent_service
    if _agent_service is None:
        _agent_service = AgentService()
    return _agent_service
