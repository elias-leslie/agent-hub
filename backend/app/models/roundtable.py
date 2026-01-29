"""Roundtable multi-agent collaboration models."""

from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class RoundtableSession(Base):
    """Roundtable multi-agent collaboration session."""

    __tablename__ = "roundtable_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    mode: Mapped[str] = mapped_column(
        Enum("quick", "deliberation", name="roundtable_mode"),
        default="quick",
    )
    tool_mode: Mapped[str] = mapped_column(
        Enum("read_only", "yolo", name="roundtable_tool_mode"),
        default="read_only",
    )
    status: Mapped[str] = mapped_column(
        Enum("active", "completed", "failed", name="roundtable_status"),
        default="active",
    )
    memory_group_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    messages = relationship(
        "RoundtableMessage", back_populates="session", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_roundtable_sessions_project_created", "project_id", "created_at"),)


class RoundtableMessage(Base):
    """Individual message in a roundtable session."""

    __tablename__ = "roundtable_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("roundtable_sessions.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(20))  # user, assistant, system
    agent_type: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # claude, gemini (null for user/system)
    content: Mapped[str] = mapped_column(Text)
    tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    session = relationship("RoundtableSession", back_populates="messages")

    __table_args__ = (
        Index("ix_roundtable_messages_session_created", "session_id", "created_at"),
        Index("ix_roundtable_messages_session_agent", "session_id", "agent_type"),
    )
