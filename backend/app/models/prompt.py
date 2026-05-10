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
from sqlalchemy.dialects.postgresql import UUID
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
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    boot_eligible: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    exclude_agents: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    owner_agent_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=True
    )
    prompt_type: Mapped[str] = mapped_column(
        String(50), default="standard", server_default="standard"
    )
    deletion_locked: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    agent_assignments: Mapped[list[AgentPrompt]] = relationship(
        "AgentPrompt", back_populates="prompt", cascade="all, delete-orphan", lazy="raise"
    )
    owner_agent: Mapped[Any | None] = relationship("Agent", lazy="raise")
    revisions: Mapped[list[PromptRevision]] = relationship(
        "PromptRevision", back_populates="prompt", lazy="raise"
    )

    __table_args__ = (
        Index("ix_prompts_is_global", "is_global", postgresql_where=(is_global == True)),  # noqa: E712
        Index("ix_prompts_owner_agent_id", "owner_agent_id"),
        Index("ix_prompts_prompt_type", "prompt_type"),
    )

    def __repr__(self) -> str:
        return f"<Prompt id={self.id} slug={self.slug!r} global={self.is_global}>"


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


class PromptRevision(Base):
    """Immutable snapshot of a prompt revision for audit and rollback."""

    __tablename__ = "prompt_revisions"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid()
    )
    prompt_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("prompts.id", ondelete="SET NULL"), nullable=True
    )
    prompt_slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    prompt_name: Mapped[str] = mapped_column(String(200), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_global: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    exclude_agents: Mapped[list[str]] = mapped_column(JSON, default=list, server_default="[]")
    owner_agent_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prompt_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="standard", server_default="standard"
    )
    deletion_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    boot_eligible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    changed_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    prompt: Mapped[Prompt | None] = relationship("Prompt", back_populates="revisions", lazy="raise")

    __table_args__ = (
        Index("ix_prompt_revisions_prompt_id", "prompt_id"),
        Index("ix_prompt_revisions_prompt_slug_created", "prompt_slug", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<PromptRevision id={self.id!r} slug={self.prompt_slug!r} action={self.action!r}>"
