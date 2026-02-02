"""Agent data transfer object."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.models import Agent


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
    is_active: bool
    is_coding_agent: bool
    tool_permissions: dict[str, Any] | None
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
            temperature=agent.temperature,
            is_active=agent.is_active,
            is_coding_agent=agent.is_coding_agent,
            tool_permissions=agent.tool_permissions,
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
            "is_active": self.is_active,
            "is_coding_agent": self.is_coding_agent,
            "tool_permissions": self.tool_permissions,
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
            is_active=data.get("is_active", True),
            is_coding_agent=data.get("is_coding_agent", False),
            tool_permissions=data.get("tool_permissions"),
            version=data.get("version", 1),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )
