"""Agent service with CRUD operations and Redis caching.

Provides:
- CRUD operations for agents
- Redis caching for frequently accessed agents
- Version tracking for audit history
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import redis.asyncio as redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Agent, AgentVersion

logger = logging.getLogger(__name__)

# Cache configuration
CACHE_PREFIX = "agent-hub:agent:"
CACHE_TTL = 300  # 5 minutes


@dataclass
class AgentDTO:
    """Data transfer object for Agent."""

    id: int
    slug: str
    name: str
    description: str | None
    system_prompt: str
    primary_model_id: str
    fallback_models: list[str]
    escalation_model_id: str | None
    strategies: dict[str, Any]
    mandate_tags: list[str]
    temperature: float
    max_tokens: int | None
    is_active: bool
    version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, agent: Agent) -> "AgentDTO":
        """Create DTO from SQLAlchemy model."""
        return cls(
            id=agent.id,
            slug=agent.slug,
            name=agent.name,
            description=agent.description,
            system_prompt=agent.system_prompt,
            primary_model_id=agent.primary_model_id,
            fallback_models=agent.fallback_models or [],
            escalation_model_id=agent.escalation_model_id,
            strategies=agent.strategies or {},
            mandate_tags=agent.mandate_tags or [],
            temperature=agent.temperature,
            max_tokens=agent.max_tokens,
            is_active=agent.is_active,
            version=agent.version,
            created_at=agent.created_at,
            updated_at=agent.updated_at,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "system_prompt": self.system_prompt,
            "primary_model_id": self.primary_model_id,
            "fallback_models": self.fallback_models,
            "escalation_model_id": self.escalation_model_id,
            "strategies": self.strategies,
            "mandate_tags": self.mandate_tags,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "is_active": self.is_active,
            "version": self.version,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentDTO":
        """Create DTO from dictionary."""
        return cls(
            id=data["id"],
            slug=data["slug"],
            name=data["name"],
            description=data.get("description"),
            system_prompt=data["system_prompt"],
            primary_model_id=data["primary_model_id"],
            fallback_models=data.get("fallback_models", []),
            escalation_model_id=data.get("escalation_model_id"),
            strategies=data.get("strategies", {}),
            mandate_tags=data.get("mandate_tags", []),
            temperature=data.get("temperature", 0.7),
            max_tokens=data.get("max_tokens"),
            is_active=data.get("is_active", True),
            version=data.get("version", 1),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )


class AgentService:
    """Service for agent CRUD operations with Redis caching."""

    def __init__(self, redis_url: str | None = None):
        """Initialize agent service.

        Args:
            redis_url: Redis connection URL. Falls back to settings.
        """
        self._redis_url = redis_url or settings.agent_hub_redis_url
        self._client: redis.Redis | None = None

    async def _get_redis(self) -> redis.Redis:
        """Get or create Redis client."""
        if self._client is None:
            self._client = redis.from_url(
                self._redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._client

    def _cache_key(self, slug: str) -> str:
        """Generate cache key for an agent slug."""
        return f"{CACHE_PREFIX}{slug}"

    async def _get_from_cache(self, slug: str) -> AgentDTO | None:
        """Get agent from cache."""
        try:
            client = await self._get_redis()
            cached = await client.get(self._cache_key(slug))
            if cached:
                logger.debug(f"Cache hit for agent: {slug}")
                return AgentDTO.from_dict(json.loads(cached))
        except Exception as e:
            logger.warning(f"Cache get error for {slug}: {e}")
        return None

    async def _set_in_cache(self, agent: AgentDTO) -> None:
        """Set agent in cache."""
        try:
            client = await self._get_redis()
            await client.setex(
                self._cache_key(agent.slug),
                CACHE_TTL,
                json.dumps(agent.to_dict()),
            )
            logger.debug(f"Cached agent: {agent.slug}")
        except Exception as e:
            logger.warning(f"Cache set error for {agent.slug}: {e}")

    async def _invalidate_cache(self, slug: str) -> None:
        """Invalidate agent cache entry."""
        try:
            client = await self._get_redis()
            await client.delete(self._cache_key(slug))
            logger.debug(f"Invalidated cache for agent: {slug}")
        except Exception as e:
            logger.warning(f"Cache invalidate error for {slug}: {e}")

    async def get_by_slug(self, db: AsyncSession, slug: str) -> AgentDTO | None:
        """Get agent by slug with caching.

        Args:
            db: Database session
            slug: Agent slug (e.g., "coder", "planner")

        Returns:
            AgentDTO if found, None otherwise
        """
        # Check cache first
        cached = await self._get_from_cache(slug)
        if cached:
            return cached

        # Query database
        result = await db.execute(
            select(Agent).where(Agent.slug == slug, Agent.is_active == True)  # noqa: E712
        )
        agent = result.scalar_one_or_none()

        if agent:
            dto = AgentDTO.from_model(agent)
            await self._set_in_cache(dto)
            return dto

        return None

    async def get_by_id(self, db: AsyncSession, agent_id: int) -> AgentDTO | None:
        """Get agent by ID.

        Args:
            db: Database session
            agent_id: Agent ID

        Returns:
            AgentDTO if found, None otherwise
        """
        result = await db.execute(select(Agent).where(Agent.id == agent_id))
        agent = result.scalar_one_or_none()

        if agent:
            return AgentDTO.from_model(agent)

        return None

    async def list_agents(
        self,
        db: AsyncSession,
        *,
        active_only: bool = True,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AgentDTO]:
        """List agents with filtering.

        Args:
            db: Database session
            active_only: Only return active agents
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of AgentDTOs
        """
        query = select(Agent)

        if active_only:
            query = query.where(Agent.is_active == True)  # noqa: E712

        query = query.order_by(Agent.slug).limit(limit).offset(offset)

        result = await db.execute(query)
        agents = result.scalars().all()

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
        mandate_tags: list[str] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        is_active: bool = True,
        changed_by: str | None = None,
    ) -> AgentDTO:
        """Create a new agent.

        Args:
            db: Database session
            slug: Unique identifier (e.g., "coder")
            name: Display name
            system_prompt: The agent's system prompt
            primary_model_id: Default model to use
            description: Optional description
            fallback_models: Ordered list of fallback models
            escalation_model_id: Model for escalation
            strategies: Provider-specific configs
            mandate_tags: Tags for mandate injection
            temperature: Default temperature
            max_tokens: Default max tokens
            is_active: Whether agent is active
            changed_by: User/system making the change

        Returns:
            Created AgentDTO
        """
        agent = Agent(
            slug=slug,
            name=name,
            description=description,
            system_prompt=system_prompt,
            primary_model_id=primary_model_id,
            fallback_models=fallback_models or [],
            escalation_model_id=escalation_model_id,
            strategies=strategies or {},
            mandate_tags=mandate_tags or [],
            temperature=temperature,
            max_tokens=max_tokens,
            is_active=is_active,
            version=1,
        )

        db.add(agent)
        await db.commit()
        await db.refresh(agent)

        dto = AgentDTO.from_model(agent)

        # Create initial version record
        version_record = AgentVersion(
            agent_id=agent.id,
            version=1,
            config_snapshot=dto.to_dict(),
            changed_by=changed_by,
            change_reason="Initial creation",
        )
        db.add(version_record)
        await db.commit()

        # Cache the new agent
        await self._set_in_cache(dto)

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
        mandate_tags: list[str] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        is_active: bool | None = None,
        changed_by: str | None = None,
        change_reason: str | None = None,
    ) -> AgentDTO | None:
        """Update an agent.

        Uses optimistic locking via version field.

        Args:
            db: Database session
            agent_id: Agent ID to update
            ... (fields to update)
            changed_by: User/system making the change
            change_reason: Why the change was made

        Returns:
            Updated AgentDTO if successful, None if not found
        """
        # Get current agent
        result = await db.execute(select(Agent).where(Agent.id == agent_id))
        agent = result.scalar_one_or_none()

        if not agent:
            return None

        old_slug = agent.slug

        # Update fields
        if name is not None:
            agent.name = name
        if description is not None:
            agent.description = description
        if system_prompt is not None:
            agent.system_prompt = system_prompt
        if primary_model_id is not None:
            agent.primary_model_id = primary_model_id
        if fallback_models is not None:
            agent.fallback_models = fallback_models
        if escalation_model_id is not None:
            agent.escalation_model_id = escalation_model_id
        if strategies is not None:
            agent.strategies = strategies
        if mandate_tags is not None:
            agent.mandate_tags = mandate_tags
        if temperature is not None:
            agent.temperature = temperature
        if max_tokens is not None:
            agent.max_tokens = max_tokens
        if is_active is not None:
            agent.is_active = is_active

        # Increment version (updated_at handled by DB onupdate trigger)
        agent.version += 1

        await db.commit()
        await db.refresh(agent)

        dto = AgentDTO.from_model(agent)

        # Create version record
        version_record = AgentVersion(
            agent_id=agent.id,
            version=agent.version,
            config_snapshot=dto.to_dict(),
            changed_by=changed_by,
            change_reason=change_reason or "Updated",
        )
        db.add(version_record)
        await db.commit()

        # Invalidate cache
        await self._invalidate_cache(old_slug)
        # Re-cache with new data
        await self._set_in_cache(dto)

        logger.info(f"Updated agent: {agent.slug} to version {agent.version}")
        return dto

    async def delete(
        self,
        db: AsyncSession,
        agent_id: int,
        *,
        hard_delete: bool = False,
    ) -> bool:
        """Delete an agent.

        Args:
            db: Database session
            agent_id: Agent ID to delete
            hard_delete: If True, permanently delete. If False, soft delete (set is_active=False)

        Returns:
            True if deleted, False if not found
        """
        result = await db.execute(select(Agent).where(Agent.id == agent_id))
        agent = result.scalar_one_or_none()

        if not agent:
            return False

        slug = agent.slug

        if hard_delete:
            await db.delete(agent)
        else:
            agent.is_active = False
            # updated_at handled by DB onupdate trigger

        await db.commit()

        # Invalidate cache
        await self._invalidate_cache(slug)

        logger.info(f"{'Deleted' if hard_delete else 'Deactivated'} agent: {slug}")
        return True

    async def get_version_history(
        self,
        db: AsyncSession,
        agent_id: int,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Get version history for an agent.

        Args:
            db: Database session
            agent_id: Agent ID
            limit: Maximum versions to return

        Returns:
            List of version records (newest first)
        """
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

    async def close(self) -> None:
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None


# Singleton instance
_agent_service: AgentService | None = None


def get_agent_service() -> AgentService:
    """Get the singleton agent service instance."""
    global _agent_service
    if _agent_service is None:
        _agent_service = AgentService()
    return _agent_service
