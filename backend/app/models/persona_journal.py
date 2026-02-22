"""PersonaJournal model — dated entries for persona temporal continuity."""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class PersonaJournal(Base):
    """Daily journal entry for the persona.

    Provides temporal continuity — the persona can record observations,
    decisions, learnings, and user insights. Recent entries are injected
    into the persona's context for full prompt mode.
    """

    __tablename__ = "persona_journal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    persona_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("persona.id", ondelete="CASCADE"), nullable=False
    )
    entry_date: Mapped[date] = mapped_column(Date, nullable=False, server_default=func.current_date())
    content: Mapped[str] = mapped_column(Text, nullable=False)
    entry_type: Mapped[str] = mapped_column(String(50), nullable=False, default="observation")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    persona = relationship("Persona", lazy="raise")

    __table_args__ = (
        Index("ix_persona_journal_persona_date", "persona_id", entry_date.desc()),
    )
