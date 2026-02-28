"""Prompt management models for DB-backed prompt composition."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Prompt(Base):
    """Reusable prompt template stored in DB.

    Prompts can be global (injected for all agents) or assigned to specific
    agents via AgentPrompt with a role and priority.
    """

    __tablename__ = "prompts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_global: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    exclude_agents: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    agent_assignments: Mapped[list[AgentPrompt]] = relationship(
        "AgentPrompt", back_populates="prompt", cascade="all, delete-orphan", lazy="raise"
    )

    __table_args__ = (
        Index("ix_prompts_is_global", "is_global", postgresql_where=(is_global == True)),  # noqa: E712
    )


class AgentPrompt(Base):
    """Join table assigning prompts to agents with role and priority."""

    __tablename__ = "agent_prompts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agents.id", ondelete="CASCADE")
    )
    prompt_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("prompts.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(100))
    priority: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    agent: Mapped[Any] = relationship("Agent", back_populates="prompt_assignments", lazy="raise")
    prompt: Mapped[Prompt] = relationship("Prompt", back_populates="agent_assignments", lazy="raise")

    __table_args__ = (
        UniqueConstraint("agent_id", "prompt_id", name="uq_agent_prompts_agent_id_prompt_id"),
        Index("ix_agent_prompts_agent_id", "agent_id"),
        Index("ix_agent_prompts_role", "role"),
    )
