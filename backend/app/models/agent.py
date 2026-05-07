"""Agent configuration and versioning models."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Agent(Base):
    """AI agent configuration with model routing and mandate injection.

    Database-backed AI agent configuration. Agents define:
    - System prompt and behavior
    - Model selection and fallback chain
    - Mandate tags for automatic context injection
    - Temperature and other inference parameters
    """

    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(50), unique=True, index=True)  # "coder", "planner"
    name: Mapped[str] = mapped_column(String(100))  # "Code Generator", "Task Planner"
    description: Mapped[str | None] = mapped_column(Text, nullable=True)  # Short description for UI
    system_prompt: Mapped[str] = mapped_column(Text)  # The agent's system prompt
    primary_model_id: Mapped[str] = mapped_column(
        String(100)
    )  # Agent Hub catalog model ID
    fallback_models: Mapped[list[str]] = mapped_column(JSON, default=list)  # Ordered fallback list
    escalation_model_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # Model for complex cases
    strategies: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict
    )  # Provider-specific configs
    temperature: Mapped[float] = mapped_column(Float, default=0.7)
    thinking_level: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # "none", "minimal", "low", "medium", "high", "xhigh"
    verbosity_level: Mapped[str | None] = mapped_column(
        String(10), nullable=True
    )  # "low", "medium", "high" — Codex/OpenAI Responses API only
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_coding_agent: Mapped[bool] = mapped_column(Boolean, default=False)
    memory_config: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, default=None
    )
    max_concurrency: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )  # Max parallel executions (None = use global default)
    max_subagent_concurrency: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )  # Max parallel subagent spawns (None = use global default)
    daily_token_budget: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )  # Max tokens per day (None = unlimited)
    hourly_request_limit: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )  # Max requests per hour (None = unlimited)
    timeout_seconds: Mapped[float | None] = mapped_column(
        Float, nullable=True, default=None
    )  # Per-agent timeout override (None = use model default)
    version: Mapped[int] = mapped_column(Integer, default=1)  # Optimistic locking
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    versions = relationship(
        "AgentVersion", back_populates="agent", cascade="all, delete-orphan", lazy="raise"
    )
    prompt_assignments = relationship(
        "AgentPrompt", back_populates="agent", cascade="all, delete-orphan", lazy="raise"
    )

    __table_args__ = (
        Index("ix_agents_slug", "slug", unique=True),
        Index("ix_agents_active", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<Agent id={self.id} slug={self.slug!r} active={self.is_active}>"


class AgentVersion(Base):
    """Audit history for agent configuration changes.

    Tracks all changes to agent configurations for compliance and debugging.
    Each update to an Agent creates a new AgentVersion with the previous state.
    """

    __tablename__ = "agent_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(Integer, ForeignKey("agents.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)  # Version number at time of snapshot
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON
    )  # Full agent config at this version
    changed_by: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # User/system that made the change
    change_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Why the change was made
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    agent = relationship("Agent", back_populates="versions", lazy="raise")

    __table_args__ = (
        Index("ix_agent_versions_agent_id", "agent_id"),
        Index("ix_agent_versions_agent_version", "agent_id", "version"),
    )

    def __repr__(self) -> str:
        return f"<AgentVersion id={self.id} agent_id={self.agent_id} version={self.version}>"
