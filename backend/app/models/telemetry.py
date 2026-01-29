"""Telemetry and logging models."""

from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class RequestLog(Base):
    """Audit log for all API requests with full attribution.

    Every request is logged with client, source, outcome, and performance metrics.
    Retained for 30 days for compliance and debugging.
    """

    __tablename__ = "request_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("clients.id", ondelete="SET NULL"), nullable=True
    )
    request_source: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # From X-Request-Source header
    endpoint: Mapped[str] = mapped_column(String(200))
    method: Mapped[str] = mapped_column(String(10))  # GET, POST, etc.
    status_code: Mapped[int] = mapped_column(Integer)
    rejection_reason: Mapped[str | None] = mapped_column(
        Enum(
            "missing_required_headers",
            "authentication_failed",
            "client_suspended",
            "client_blocked",
            "rate_limited",
            name="rejection_reason_enum",
        ),
        nullable=True,
    )
    # Performance metrics
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Request context
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Tool/agent tracking for unified metrics
    agent_slug: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    tool_type: Mapped[str] = mapped_column(
        Enum("api", "cli", "sdk", name="tool_type_enum"),
        default="api",
    )
    # Granular tool tracking
    tool_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )  # e.g., "st complete", "client.complete"
    source_path: Mapped[str | None] = mapped_column(
        String(500), nullable=True
    )  # Caller file path for debugging
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    client = relationship("Client", back_populates="request_logs")

    __table_args__ = (
        Index("ix_request_logs_client_id", "client_id"),
        Index("ix_request_logs_created_at", "created_at"),
        Index("ix_request_logs_status_code", "status_code"),
        Index("ix_request_logs_client_created", "client_id", "created_at"),
        Index("ix_request_logs_agent_slug", "agent_slug"),
    )


class TruncationEvent(Base):
    """Telemetry for response truncations (output limit events)."""

    __tablename__ = "truncation_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
    )
    model: Mapped[str] = mapped_column(String(100), index=True)
    endpoint: Mapped[str] = mapped_column(String(50))  # "complete", "stream"
    max_tokens_requested: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    model_limit: Mapped[int] = mapped_column(Integer)
    was_capped: Mapped[int] = mapped_column(
        Integer, default=0
    )  # 1 if request was capped to model limit
    project_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_truncation_events_model_created", "model", "created_at"),
        Index("ix_truncation_events_created", "created_at"),
    )
