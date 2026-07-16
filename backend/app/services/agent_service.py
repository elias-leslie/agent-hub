"""Agent service with CRUD operations and Redis caching.

Provides:
- CRUD operations for agents
- Redis caching for frequently accessed agents
- Version tracking for audit history
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants import resolve_model
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
from app.services.memory.context_builder_settings import normalize_memory_config
from app.services.owned_prompt_service import sync_agent_system_prompt
from app.services.persona_identity import PERSONA_SLUG, get_persona_display_name
from app.services.prompt_catalog import build_agent_system_prompt_slug
from app.services.prompt_service import get_prompt_by_slug

logger = logging.getLogger(__name__)

# Export public API
__all__ = ["AgentDTO", "AgentService", "get_agent_service"]


async def _resolve_system_prompt(db: AsyncSession, agent: Any) -> str:
    prompt = await get_prompt_by_slug(db, build_agent_system_prompt_slug(agent.slug))
    if prompt is not None:
        # Presence makes the owned prompt row authoritative. Disabled (or
        # deliberately empty) means "inject nothing"; only a truly absent,
        # not-yet-migrated row may use the Agent compatibility mirror.
        return prompt.content.strip() if prompt.enabled else ""
    return agent.system_prompt


async def _apply_display_name_overrides(db: AsyncSession, dto: AgentDTO) -> AgentDTO:
    """Resolve shared display names from their live authority rows."""
    if dto.slug != PERSONA_SLUG:
        return dto
    display_name = await get_persona_display_name(db, fallback=dto.name)
    if display_name == dto.name:
        return dto
    return replace(dto, name=display_name)


def _canonicalize_model_id(model_id: str | None) -> str | None:
    if not model_id:
        return None
    return resolve_model(model_id)


def _canonicalize_model_chain(models: list[str] | None) -> list[str]:
    seen: set[str] = set()
    canonical: list[str] = []
    for model in models or []:
        resolved = _canonicalize_model_id(model)
        if not resolved or resolved in seen:
            continue
        seen.add(resolved)
        canonical.append(resolved)
    return canonical


class AgentService:
    """Service for agent CRUD operations with Redis caching."""

    def __init__(self, redis_url: str | None = None):
        """Initialize agent service."""
        url = redis_url or settings.agent_hub_redis_url
        self._cache = AgentCache(url)

    async def get_by_slug(
        self,
        db: AsyncSession,
        slug: str,
        *,
        active_only: bool = True,
    ) -> AgentDTO | None:
        """Get agent by slug with caching."""
        if active_only:
            cached = await self._cache.get(slug)
            if cached:
                # The owned prompt row is the live authority. AgentDTO caching
                # must not turn its compatibility mirror into a second prompt
                # source for up to CACHE_TTL seconds after a prompt edit.
                resolved_system_prompt = await _resolve_system_prompt(db, cached)
                if resolved_system_prompt != cached.system_prompt:
                    cached = replace(
                        cached,
                        system_prompt=resolved_system_prompt,
                    )
                    await self._cache.set(cached)
                return await _apply_display_name_overrides(db, cached)

        agent = await get_agent_by_slug(db, slug, active_only=active_only)
        if agent:
            dto = AgentDTO.from_model(
                agent,
                system_prompt_override=await _resolve_system_prompt(db, agent),
            )
            dto = await _apply_display_name_overrides(db, dto)
            if active_only:
                await self._cache.set(dto)
            return dto

        return None

    async def get_by_id(self, db: AsyncSession, agent_id: int) -> AgentDTO | None:
        """Get agent by ID."""
        agent = await get_agent_by_id(db, agent_id)
        if not agent:
            return None
        dto = AgentDTO.from_model(
            agent,
            system_prompt_override=await _resolve_system_prompt(db, agent),
        )
        return await _apply_display_name_overrides(db, dto)

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
        dtos = [
            AgentDTO.from_model(
                agent,
                system_prompt_override=await _resolve_system_prompt(db, agent),
            )
            for agent in agents
        ]
        return [await _apply_display_name_overrides(db, dto) for dto in dtos]

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
        memory_config: dict[str, Any] | None = None,
        max_concurrency: int | None = None,
        max_subagent_concurrency: int | None = None,
        daily_token_budget: int | None = None,
        hourly_request_limit: int | None = None,
        changed_by: str | None = None,
    ) -> AgentDTO:
        """Create a new agent."""
        agent = create_agent_model(
            slug=slug,
            name=name,
            description=description,
            system_prompt=system_prompt,
            primary_model_id=_canonicalize_model_id(primary_model_id) or primary_model_id,
            fallback_models=_canonicalize_model_chain(fallback_models),
            escalation_model_id=_canonicalize_model_id(escalation_model_id),
            strategies=strategies,
            temperature=temperature,
            thinking_level=thinking_level,
            verbosity_level=verbosity_level,
            is_active=is_active,
            is_coding_agent=is_coding_agent,
            memory_config=normalize_memory_config(memory_config),
            max_concurrency=max_concurrency,
            max_subagent_concurrency=max_subagent_concurrency,
            daily_token_budget=daily_token_budget,
            hourly_request_limit=hourly_request_limit,
        )
        db.add(agent)
        await db.flush()
        await sync_agent_system_prompt(
            db,
            agent=agent,
            system_prompt=system_prompt,
            changed_by=changed_by,
            change_reason="Initial agent system prompt bootstrap",
        )
        await db.commit()
        await db.refresh(agent)
        dto = AgentDTO.from_model(agent, system_prompt_override=system_prompt)
        await create_version_record(db, agent.id, 1, dto.to_dict(), changed_by, "Initial creation")
        await self._cache.set(dto)
        logger.info(f"Created agent: {slug}")
        return dto

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
        memory_config: dict[str, Any] | None = None,
        max_concurrency: int | None = None,
        max_subagent_concurrency: int | None = None,
        daily_token_budget: int | None = None,
        hourly_request_limit: int | None = None,
        changed_by: str | None = None,
        change_reason: str | None = None,
    ) -> AgentDTO | None:
        """Update an agent. Uses optimistic locking via version field."""
        agent = await get_agent_by_id(db, agent_id)
        if not agent:
            return None

        memory_cfg = normalize_memory_config(memory_config) if memory_config is not None else None
        prev_slug = agent.slug
        resolved_escalation = (
            _canonicalize_model_id(escalation_model_id)
            if escalation_model_id is not None
            else None
        )
        apply_agent_updates(
            agent,
            name=name,
            description=description,
            system_prompt=system_prompt,
            primary_model_id=_canonicalize_model_id(primary_model_id),
            fallback_models=_canonicalize_model_chain(fallback_models) if fallback_models is not None else None,
            escalation_model_id=resolved_escalation,
            strategies=strategies,
            temperature=temperature,
            thinking_level=thinking_level,
            verbosity_level=verbosity_level,
            is_active=is_active,
            is_coding_agent=is_coding_agent,
            memory_config=memory_cfg,
            max_concurrency=max_concurrency,
            max_subagent_concurrency=max_subagent_concurrency,
            daily_token_budget=daily_token_budget,
            hourly_request_limit=hourly_request_limit,
        )
        if escalation_model_id is not None:
            agent.escalation_model_id = resolved_escalation
        agent.version += 1
        if system_prompt is not None:
            await sync_agent_system_prompt(
                db,
                agent=agent,
                system_prompt=system_prompt,
                changed_by=changed_by,
                change_reason=change_reason or "Updated agent system prompt",
            )
        await db.commit()
        await db.refresh(agent)
        dto = AgentDTO.from_model(
            agent,
            system_prompt_override=await _resolve_system_prompt(db, agent),
        )
        await create_version_record(
            db, agent.id, agent.version, dto.to_dict(), changed_by, change_reason or "Updated"
        )
        await self._cache.invalidate(prev_slug)
        await self._cache.set(dto)
        logger.info(f"Updated agent: {agent.slug} to version {agent.version}")
        return dto

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

    async def invalidate_slug(self, slug: str) -> None:
        await self._cache.invalidate(slug)


# Singleton instance
_agent_service: AgentService | None = None


def get_agent_service() -> AgentService:
    """Get the singleton agent service instance."""
    global _agent_service
    if _agent_service is None:
        _agent_service = AgentService()
    return _agent_service
