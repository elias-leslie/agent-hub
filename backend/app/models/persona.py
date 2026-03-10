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
from sqlalchemy.dialects.postgresql import JSONB
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
    name: Mapped[str] = mapped_column(String(100), nullable=False, default="Jenny")
    personality: Mapped[str | None] = mapped_column(Text, nullable=True)
    personality_previous: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_context_previous: Mapped[str | None] = mapped_column(Text, nullable=True)
    voice_id: Mapped[str] = mapped_column(String(200), default="en-US-AriaNeural")
    voice_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    heartbeat_interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    execution_state: Mapped[str] = mapped_column(
        String(16), default="active", server_default="active"
    )
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    greeting: Mapped[str | None] = mapped_column(Text, nullable=True)
    onboarding_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    onboarding_phase: Mapped[str] = mapped_column(
        String(20), default="not_started", server_default="not_started"
    )
    # Session auto-reset configuration
    session_reset_mode: Mapped[str] = mapped_column(
        String(10), default="off", server_default="off"
    )  # "off" / "daily" / "idle"
    session_reset_hour: Mapped[int] = mapped_column(
        Integer, default=9, server_default="9"
    )  # 0-23, for daily mode
    session_reset_idle_minutes: Mapped[int] = mapped_column(
        Integer, default=120, server_default="120"
    )  # For idle mode

    # Onboarding attempt counter for auto-approval after max rejections
    onboarding_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # Configurable limits (adjustable via UI/API)
    limits: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

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
