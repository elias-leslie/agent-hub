"""Agent data transfer object."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.models import Agent
from app.services.memory.context_builder_settings import normalize_memory_config


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
    temperature: float
    thinking_level: str | None
    verbosity_level: str | None
    is_active: bool
    is_coding_agent: bool
    memory_config: dict[str, Any] | None
    max_concurrency: int | None
    max_subagent_concurrency: int | None
    daily_token_budget: int | None
    hourly_request_limit: int | None
    version: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_model(cls, agent: Agent, *, system_prompt_override: str | None = None) -> "AgentDTO":
        """Create DTO from SQLAlchemy model."""
        return cls(
            id=agent.id,
            slug=agent.slug,
            name=agent.name,
            description=agent.description,
            system_prompt=system_prompt_override if system_prompt_override is not None else agent.system_prompt,
            primary_model_id=agent.primary_model_id,
            fallback_models=agent.fallback_models or [],
            escalation_model_id=agent.escalation_model_id,
            strategies=agent.strategies or {},
            temperature=agent.temperature,
            thinking_level=agent.thinking_level,
            verbosity_level=agent.verbosity_level,
            is_active=agent.is_active,
            is_coding_agent=agent.is_coding_agent,
            memory_config=normalize_memory_config(agent.memory_config),
            max_concurrency=agent.max_concurrency,
            max_subagent_concurrency=agent.max_subagent_concurrency,
            daily_token_budget=agent.daily_token_budget,
            hourly_request_limit=agent.hourly_request_limit,
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
            "temperature": self.temperature,
            "thinking_level": self.thinking_level,
            "verbosity_level": self.verbosity_level,
            "is_active": self.is_active,
            "is_coding_agent": self.is_coding_agent,
            "memory_config": self.memory_config,
            "max_concurrency": self.max_concurrency,
            "max_subagent_concurrency": self.max_subagent_concurrency,
            "daily_token_budget": self.daily_token_budget,
            "hourly_request_limit": self.hourly_request_limit,
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
            temperature=data.get("temperature", 0.7),
            thinking_level=data.get("thinking_level"),
            verbosity_level=data.get("verbosity_level"),
            is_active=data.get("is_active", True),
            is_coding_agent=data.get("is_coding_agent", False),
            memory_config=normalize_memory_config(data.get("memory_config")),
            max_concurrency=data.get("max_concurrency"),
            max_subagent_concurrency=data.get("max_subagent_concurrency"),
            daily_token_budget=data.get("daily_token_budget"),
            hourly_request_limit=data.get("hourly_request_limit"),
            version=data.get("version", 1),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )
