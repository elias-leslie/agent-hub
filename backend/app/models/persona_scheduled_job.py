"""Persona scheduled job model — cron, interval, and one-shot jobs."""

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
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class PersonaScheduledJob(Base):
    """A scheduled job owned by a persona.

    Supports three schedule types:
    - "at": one-shot at a specific ISO datetime
    - "every": recurring at a fixed interval (milliseconds)
    - "cron": recurring via cron expression

    Payload types:
    - "agent_turn": inject message as user input to complete_internal
    - "push": send a push notification directly
    - "self_honing": run Jenny's scheduled self-honing loop directly
    """

    __tablename__ = "persona_scheduled_jobs"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid()
    )
    persona_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("persona.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    schedule_type: Mapped[str] = mapped_column(String(20), nullable=False)  # at / every / cron
    schedule_value: Mapped[str] = mapped_column(String(100), nullable=False)
    schedule_timezone: Mapped[str] = mapped_column(String(50), default="UTC", server_default="UTC")
    payload_type: Mapped[str] = mapped_column(
        String(20), default="agent_turn", server_default="agent_turn"
    )  # agent_turn / push / self_honing
    payload_message: Mapped[str] = mapped_column(Text, nullable=False)
    payload_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    delivery: Mapped[str] = mapped_column(
        String(20), default="none", server_default="none"
    )  # none / push
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    run_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_runs: Mapped[int | None] = mapped_column(Integer, nullable=True)  # null = unlimited
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    persona = relationship("Persona", lazy="raise")

    __table_args__ = (
        Index("ix_persona_scheduled_jobs_next_run", "enabled", "next_run_at"),
    )

    def __repr__(self) -> str:
        return f"<PersonaScheduledJob name={self.name!r} type={self.schedule_type!r} enabled={self.enabled}>"
