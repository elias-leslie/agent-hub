"""Session and event models for full observability."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    Float,
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
from .field_lengths import EXTERNAL_ID_MAX_LENGTH


class SessionEventType:
    """Event types for session timeline."""

    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"
    SYSTEM_MESSAGE = "system_message"
    THINKING = "thinking"
    TOOL_USE = "tool_use"
    TOOL_RESULT = "tool_result"
    MEMORY_INJECT = "memory_inject"
    MEMORY_CITE = "memory_cite"
    ERROR = "error"
    SUBAGENT_RESULT = "subagent_result"
    TOOL_AUDIT = "tool_audit"


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

    # Session branching support
    parent_session_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    fork_point_turn: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pending_patches: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, default=None
    )  # Uncommitted file changes for mutex pattern
    branch_status: Mapped[str | None] = mapped_column(
        Enum("active", "promoted", "discarded", name="branch_status_enum"),
        nullable=True,
        default=None,
    )
    workstream_status: Mapped[str | None] = mapped_column(
        Enum(
            "authoritative",
            "superseded",
            "retired",
            name="workstream_status_enum",
        ),
        nullable=True,
        default=None,
    )
    workstream_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    workstream_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Outcome tracking for branched sessions
    manual_outcome: Mapped[str | None] = mapped_column(
        Enum("selected", "discarded", name="manual_outcome_enum"),
        nullable=True,
        default=None,
    )  # User-set outcome
    # Agent that processed this session (e.g., "coder", "validator")
    agent_slug: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    # External ID for caller-defined cost aggregation (e.g., task ID, user ID, billing entity)
    external_id: Mapped[str | None] = mapped_column(
        String(EXTERNAL_ID_MAX_LENGTH), nullable=True, index=True
    )
    # Session type for categorizing workflows
    session_type: Mapped[str] = mapped_column(
        Enum(
            "completion",
            "chat",
            "roundtable",
            "image_generation",
            "agent",  # Long-running automated agent sessions (24h idle timeout)
            "claude_code",  # Claude Code CLI sessions
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
    # Git branch at session creation time (for continuity scoping on close)
    current_branch: Mapped[str | None] = mapped_column(String(200), nullable=True)
    declared_scope_paths: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=list)
    observed_read_paths: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=list)
    observed_write_paths: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=list)
    scope_confidence: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    health_detail: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Session summary (populated by summary generator after session close)
    summary_oneliner: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_outcome: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # completed | failed | abandoned | partial
    summary_files_touched: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    summary_branch: Mapped[str | None] = mapped_column(String(200), nullable=True)
    summary_git_digest: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    client = relationship("Client", back_populates="sessions", lazy="raise")
    events = relationship(
        "SessionEvent", back_populates="session", cascade="all, delete-orphan", lazy="raise"
    )
    cost_logs = relationship(
        "CostLog", back_populates="session", cascade="all, delete-orphan", lazy="raise"
    )
    injection_metrics = relationship(
        "MemoryInjectionMetric", back_populates="session", lazy="raise"
    )
    # Session branching relationships
    parent_session = relationship(
        "Session",
        remote_side="Session.id",
        foreign_keys=[parent_session_id],
        backref="child_branches",
        lazy="raise",
    )

    __table_args__ = (
        Index("ix_sessions_project_created", "project_id", "created_at"),
        Index("ix_sessions_parent", "parent_session_id"),
        Index("ix_sessions_project_heartbeat", "project_id", "last_heartbeat_at"),
        Index("ix_sessions_status_last_activity", "status", "last_activity_at"),
    )

    def __repr__(self) -> str:
        return f"<Session id={self.id!r} project={self.project_id!r} status={self.status!r}>"


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
    session = relationship("Session", back_populates="cost_logs", lazy="raise")

    __table_args__ = (
        Index("ix_cost_logs_session", "session_id"),
        Index("ix_cost_logs_created", "created_at"),
    )


class SessionEvent(Base):
    """Unified event log for full session observability.

    Captures all session activity: messages, thinking, tool calls, memory operations.
    Enables Claude Code-like experience showing full execution timeline.
    """

    __tablename__ = "session_events"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid()
    )
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    turn: Mapped[int] = mapped_column(Integer, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)

    role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)

    tool_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tool_input: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    tool_output: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)

    agent_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    agent_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session = relationship("Session", back_populates="events", lazy="raise")

    __table_args__ = (
        UniqueConstraint("session_id", "turn", "sequence", name="uq_session_turn_sequence"),
        Index("ix_session_events_session_turn", "session_id", "turn", "sequence"),
        Index("ix_session_events_type", "event_type"),
        Index("ix_session_events_tool", "tool_name"),
    )

    def __repr__(self) -> str:
        return f"<SessionEvent id={self.id!r} type={self.event_type!r} turn={self.turn}>"


class SessionSummarySegment(Base):
    """Incremental summary segment for a session.

    Each time a session is summarized (e.g., Stop hook fires after /resume),
    a new segment row is created rather than overwriting the session's summary
    columns. This allows long-running sessions to have multiple "Recent Activity"
    entries, each reflecting a distinct work period.
    """

    __tablename__ = "session_summary_segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    summary_oneliner: Mapped[str] = mapped_column(Text, nullable=False)
    summary_outcome: Mapped[str | None] = mapped_column(String(20), nullable=True)
    summary_git_digest: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_branch: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    session = relationship("Session", lazy="raise")

    __table_args__ = (
        Index("idx_segments_session_created", "session_id", "created_at"),
    )
