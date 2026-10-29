"""Session and event models for full observability."""

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
    UniqueConstraint,
    event,
    func,
    inspect,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.services.secret_redaction import redact_text, redact_value

from .base import Base, redact_loaded
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
    # The tool loop summarized older history before a model call; the originals stay in the session.
    COMPACTION = "compaction"
    SUBAGENT_RESULT = "subagent_result"
    TOOL_AUDIT = "tool_audit"
    CHILD_SESSION_STARTED = "child_session_started"
    CHILD_SESSION_UPDATE = "child_session_update"
    CHILD_SESSION_BLOCKED = "child_session_blocked"
    CHILD_SESSION_RESULT = "child_session_result"


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
        String(36), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
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
            "pi",  # Native Pi CLI sessions
            "workflow",  # Durable multi-model workflow runs (workflow_steps)
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
        # Last-active keyset order used by the sessions list (migration d1f7b3a5c9e2).
        Index(
            "ix_sessions_last_active",
            text("(coalesce(last_activity_at, created_at)) DESC"),
            text("id DESC"),
        ),
        Index(
            "ix_sessions_project_last_active",
            "project_id",
            text("(coalesce(last_activity_at, created_at)) DESC"),
            text("id DESC"),
        ),
    )

    def __repr__(self) -> str:
        return f"<Session id={self.id!r} project={self.project_id!r} status={self.status!r}>"


class NativeContinuationTurn(Base):
    """Durable receipt for one accepted Codex native-thread turn."""

    __tablename__ = "native_continuation_turns"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid()
    )
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    generation: Mapped[int] = mapped_column(Integer, nullable=False)
    request_id: Mapped[str] = mapped_column(String(100), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_turn: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted_turn: Mapped[int] = mapped_column(Integer, nullable=False)
    context_version: Mapped[str] = mapped_column(String(100), nullable=False)
    instruction_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    tool_policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    runtime_status: Mapped[str] = mapped_column(String(20), nullable=False)
    agent_used: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="accepted")
    native_thread_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    native_turn_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reasoning_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    usage_known: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "generation",
            "request_id",
            name="uq_native_continuation_turn_request",
        ),
        Index(
            "ix_native_continuation_turn_session_generation",
            "session_id",
            "generation",
            "accepted_turn",
        ),
    )


# Marks a workflow attempt's cost row whose harness transcript the usage collector already counts (Claude Code,
# Codex). The row stays for per-attempt accounting; readers that also add the collector's totals leave it out.
NATIVE_COUNTED_NOTE = "workflow attempt; native transcript counted by the usage collector"


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
    # Provider prefix-cache accounting — the Phase 5 cache-safety signal for
    # Headroom tool-result compression (a write spike that erases token savings
    # is the documented hard fail).
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Tool-result compression attribution (blocks rewritten + tokens saved).
    compression_blocks: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    compression_tokens_before: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    compression_tokens_after: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Marginal cash cost. Subscription calls inside included limits are $0.
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    # metered | subscription | local. Subscription rows carry list-price value in api_equiv_usd.
    billing_mode: Mapped[str] = mapped_column(String(16), default="metered", server_default="metered")
    # API-equivalent value (tokens x list price). Value received, never spend.
    api_equiv_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Codex credits drawn by this call (only when included limits were exhausted).
    credits_used: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Set when a row's accounting was corrected after the fact (what changed and why).
    cost_note: Mapped[str | None] = mapped_column(String(200), nullable=True)
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
    call_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tool_input: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    _tool_output: Mapped[dict[str, Any] | None] = mapped_column("tool_output", JSON, nullable=True)
    tool_output_from_content: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    @hybrid_property
    def tool_output(self) -> dict[str, Any] | None:
        """Expose the original payload while duplicate output lives only in content.

        The explicit flag distinguishes an omitted output from an output backed by
        content without reserving or overwriting a key in native tool metadata.
        Class-level expressions continue to address the stored JSON column;
        full-text queries must include content.
        """
        if self.tool_output_from_content and isinstance(self.content, str):
            return {**(self._tool_output or {}), "output": self.content}
        return self._tool_output

    @tool_output.inplace.setter
    def _set_tool_output(self, value: dict[str, Any] | None) -> None:
        self._tool_output = value
        self.tool_output_from_content = False

    @tool_output.inplace.expression
    @classmethod
    def _tool_output_expression(cls):
        # A label retains the public hybrid identity for bulk ORM assignment;
        # returning the mapped attribute directly bypasses update_expression.
        return cls._tool_output.label("tool_output")

    @tool_output.inplace.update_expression
    @classmethod
    def _tool_output_update_expression(cls, value):
        # Bulk ORM replacement must not resurrect the previous canonical output.
        return [(cls._tool_output, value), (cls.tool_output_from_content, False)]

    def redact_secrets(self) -> None:
        """Apply the secret floor to stored text; assigns only on a match.

        Reads loaded values only: an unloaded column is not being written, and a
        lazy load inside a flush listener would need IO.
        """
        loaded = inspect(self).dict
        for attr, redact in (("content", redact_text), ("tool_input", redact_value), ("_tool_output", redact_value)):
            if attr not in loaded:
                continue
            value = loaded[attr]
            redacted = redact(value)
            if redacted is not value and redacted != value:
                setattr(self, attr, redacted)

    def compact_tool_output(self) -> None:
        """Keep exact duplicate tool-result text once, without mutating callers."""
        if (
            self.event_type == SessionEventType.TOOL_RESULT
            and isinstance(self.content, str)
            and isinstance(self._tool_output, dict)
            and isinstance(self._tool_output.get("output"), str)
            and self._tool_output["output"] == self.content
        ):
            self._tool_output = {key: value for key, value in self._tool_output.items() if key != "output"}
            self.tool_output_from_content = True

    tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # tool_use only: how much of the turn's answer (UTF-16 units) had streamed when the call started.
    content_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)

    agent_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    agent_name: Mapped[str | None] = mapped_column(String(100), nullable=True)

    transport: Mapped[str | None] = mapped_column(String(50), nullable=True)
    surface: Mapped[str | None] = mapped_column(String(100), nullable=True)
    chat_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    message_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pane_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_client: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    usage: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session = relationship("Session", back_populates="events", lazy="raise")

    __table_args__ = (
        UniqueConstraint("session_id", "turn", "sequence", name="uq_session_turn_sequence"),
        Index("ix_session_events_type", "event_type"),
        Index("ix_session_events_tool", "tool_name"),
        Index("ix_session_events_call_id", "session_id", "call_id"),
        Index("ix_session_events_session_type", "session_id", "event_type"),
        Index(
            "uq_session_events_source_event", "session_id", "source_event_id",
            unique=True, postgresql_where=text("source_event_id IS NOT NULL"),
        ),
    )

    def __repr__(self) -> str:
        return f"<SessionEvent id={self.id!r} type={self.event_type!r} turn={self.turn}>"


@event.listens_for(SessionEvent, "before_insert")
@event.listens_for(SessionEvent, "before_update")
def _redact_and_compact_session_event(_mapper, _connection, target: SessionEvent) -> None:
    # Covers direct ORM writes such as branching as well as shared event storage
    # and session ingestion. Redaction runs first so compaction still sees equal
    # content and output.
    target.redact_secrets()
    target.compact_tool_output()


_SESSION_REDACTED_FIELDS = ("provider_metadata", "workstream_note", "summary_oneliner", "summary_git_digest")
_SEGMENT_REDACTED_FIELDS = ("summary_oneliner", "summary_git_digest")


@event.listens_for(Session, "before_insert")
@event.listens_for(Session, "before_update")
def _redact_session(_mapper, _connection, target: Session) -> None:
    # Heartbeats store the hook's current/last shell command and summary in
    # provider_metadata.live_activity; summaries and workstream notes are free text.
    redact_loaded(target, _SESSION_REDACTED_FIELDS)


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


@event.listens_for(SessionSummarySegment, "before_insert")
@event.listens_for(SessionSummarySegment, "before_update")
def _redact_summary_segment(_mapper, _connection, target: SessionSummarySegment) -> None:
    redact_loaded(target, _SEGMENT_REDACTED_FIELDS)
