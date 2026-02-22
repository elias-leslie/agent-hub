"""Persona model — first-class identity layer above agents."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Persona(Base):
    """First-class persona entity with personality, voice, and identity config.

    Sits above an agent and provides a customizable, nameable identity
    with its own personality document, voice preferences, and heartbeat config.
    """

    __tablename__ = "persona"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, default="Johnny")
    personality: Mapped[str | None] = mapped_column(Text, nullable=True)
    heartbeat_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    tools_guidance: Mapped[str | None] = mapped_column(Text, nullable=True)
    voice_id: Mapped[str] = mapped_column(String(200), default="en-US-AriaNeural")
    voice_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    heartbeat_interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    greeting: Mapped[str | None] = mapped_column(Text, nullable=True)
    onboarding_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    onboarding_phase: Mapped[str] = mapped_column(
        String(20), default="not_started", server_default="not_started"
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    agent = relationship("Agent", lazy="raise")

    __table_args__ = (
        Index("ix_persona_agent_id", "agent_id", unique=True),
    )
