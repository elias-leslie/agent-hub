"""Session and message models."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
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


class Session(Base):
    """AI conversation session."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(100), index=True)
    provider: Mapped[str] = mapped_column(String(20))  # claude, gemini
    model: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(
        Enum("active", "completed", "failed", name="session_status"),
        default="active",
    )
    # Agent that processed this session (e.g., "coder", "validator")
    agent_slug: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    # External ID for caller-defined cost aggregation (e.g., task ID, user ID, billing entity)
    external_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    # Session type for categorizing workflows
    session_type: Mapped[str] = mapped_column(
        Enum(
            "completion",
            "chat",
            "roundtable",
            "image_generation",
            "agent",  # Long-running automated agent sessions (24h idle timeout)
            name="session_type_enum",
        ),
        default="completion",
    )
    # Access control - who made this request
    client_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("clients.id", ondelete="SET NULL"), nullable=True
    )
    request_source: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # From X-Request-Source header
    # Legacy session flag - True for sessions created before access control was implemented
    is_legacy: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    # Provider-specific metadata (SDK session IDs, cache info, etc.)
    provider_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, default=dict
    )
    # Multi-model support: track all models/providers used in this session
    models_used: Mapped[list[str] | None] = mapped_column(
        JSON, nullable=True, default=list
    )  # Array of model IDs used
    providers_used: Mapped[list[str] | None] = mapped_column(
        JSON, nullable=True, default=list
    )  # Array of providers used
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    client = relationship("Client", back_populates="sessions")
    messages = relationship("Message", back_populates="session", cascade="all, delete-orphan")
    cost_logs = relationship("CostLog", back_populates="session", cascade="all, delete-orphan")
    injection_metrics = relationship("MemoryInjectionMetric", back_populates="session")

    __table_args__ = (Index("ix_sessions_project_created", "project_id", "created_at"),)


class Message(Base):
    """Individual message within a session."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(20))  # user, assistant, system
    content: Mapped[str] = mapped_column(Text)
    tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Agent identifier for multi-agent sessions (roundtable, orchestration)
    agent_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    # Agent display name for UI
    agent_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Model that generated this message (for assistant messages)
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    session = relationship("Session", back_populates="messages")

    __table_args__ = (
        Index("ix_messages_session_created", "session_id", "created_at"),
        Index("ix_messages_session_agent", "session_id", "agent_id"),
    )


class CostLog(Base):
    """Token usage and cost tracking per request."""

    __tablename__ = "cost_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="CASCADE")
    )
    model: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    session = relationship("Session", back_populates="cost_logs")

    __table_args__ = (
        Index("ix_cost_logs_session", "session_id"),
        Index("ix_cost_logs_created", "created_at"),
    )
