"""
SQLAlchemy models for Agent Hub.

Tables:
- sessions: AI conversation sessions
- messages: Individual messages within sessions
- credentials: Encrypted API credentials
- cost_logs: Token usage and cost tracking
- llm_models: LLM model registry (centralized model definitions)
"""

from __future__ import annotations

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
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.constants import DEFAULT_CLAUDE_MODEL


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class Client(Base):
    """Authenticated client for API access.

    Every API request must be authenticated with a client_id and secret.
    Secrets are stored as bcrypt hashes; the plaintext is shown only once at registration.
    """

    __tablename__ = "clients"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID
    display_name: Mapped[str] = mapped_column(String(100))
    client_type: Mapped[str] = mapped_column(
        Enum("internal", "external", "service", name="client_type_enum"),
        default="external",
    )
    secret_hash: Mapped[str] = mapped_column(String(128))  # bcrypt hash
    secret_prefix: Mapped[str] = mapped_column(String(20))  # "ahc_" + first 8 chars for display
    status: Mapped[str] = mapped_column(
        Enum("active", "suspended", "blocked", name="client_status_enum"),
        default="active",
    )
    # Rate limiting
    rate_limit_rpm: Mapped[int] = mapped_column(Integer, default=60)  # Requests per minute
    rate_limit_tpm: Mapped[int] = mapped_column(Integer, default=100000)  # Tokens per minute
    # Audit fields
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suspended_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    suspension_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    sessions = relationship("Session", back_populates="client")
    request_logs = relationship("RequestLog", back_populates="client")

    __table_args__ = (
        Index("ix_clients_status", "status"),
        Index("ix_clients_display_name", "display_name"),
    )


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


class Credential(Base):
    """Encrypted API credentials."""

    __tablename__ = "credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(20), index=True)  # claude, gemini
    credential_type: Mapped[str] = mapped_column(String(50))  # api_key, oauth_token, etc.
    value_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (Index("ix_credentials_provider_type", "provider", "credential_type"),)


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


class APIKey(Base):
    """Virtual API keys for OpenAI-compatible endpoint authentication."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # SHA-256 hash
    key_prefix: Mapped[str] = mapped_column(String(20))  # "sk-ah-" + first 8 chars for display
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)  # User-friendly name
    project_id: Mapped[str] = mapped_column(String(100), index=True)  # For cost tracking
    rate_limit_rpm: Mapped[int] = mapped_column(Integer, default=60)  # Requests per minute
    rate_limit_tpm: Mapped[int] = mapped_column(Integer, default=100000)  # Tokens per minute
    is_active: Mapped[int] = mapped_column(Integer, default=1)  # 1=active, 0=revoked
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # Optional expiration

    __table_args__ = (Index("ix_api_keys_project", "project_id"),)


class WebhookSubscription(Base):
    """Webhook subscriptions for session event notifications."""

    __tablename__ = "webhook_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(String(2048))  # Callback URL
    secret: Mapped[str] = mapped_column(String(64))  # HMAC secret for signature verification
    event_types: Mapped[list[str]] = mapped_column(JSON)  # List of event types to receive
    project_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, index=True
    )  # Filter to specific project
    is_active: Mapped[int] = mapped_column(Integer, default=1)  # 1=active, 0=disabled
    description: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )  # User-friendly description
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    last_triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failure_count: Mapped[int] = mapped_column(Integer, default=0)  # Consecutive failures

    __table_args__ = (Index("ix_webhook_subscriptions_project", "project_id"),)


class UserPreferences(Base):
    """User preferences for AI interactions."""

    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(100), unique=True, index=True
    )  # Identifier for the user
    verbosity: Mapped[str] = mapped_column(
        Enum("concise", "normal", "detailed", name="verbosity_level"),
        default="normal",
    )
    tone: Mapped[str] = mapped_column(
        Enum("professional", "friendly", "technical", name="tone_type"),
        default="professional",
    )
    default_model: Mapped[str] = mapped_column(String(100), default=DEFAULT_CLAUDE_MODEL)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
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


class UsageStatLog(Base):
    """Historical usage statistics for memory episodes.

    Tracks when golden standards and other memory entries are:
    - loaded: Injected into context
    - referenced: Cited by LLM in response
    - success: Associated with positive feedback
    """

    __tablename__ = "usage_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    episode_uuid: Mapped[str] = mapped_column(String(36), index=True)
    metric_type: Mapped[str] = mapped_column(
        Enum("loaded", "referenced", "success", name="usage_metric_type"),
    )
    value: Mapped[int] = mapped_column(Integer, default=1)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_usage_stats_timestamp", "timestamp"),
        Index("ix_usage_stats_episode_metric", "episode_uuid", "metric_type"),
    )


class ClientControl(Base):
    """Kill switch control for individual clients.

    Used to enable/disable API access for specific client applications.
    When disabled=True, requests from this client are blocked with 403.
    """

    __tablename__ = "client_controls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disabled_by: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # User/admin who disabled
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)  # Reason for disabling
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Agent(Base):
    """AI agent configuration with model routing and mandate injection.

    Database-backed AI agent configuration. Agents define:
    - System prompt and behavior
    - Model selection and fallback chain
    - Mandate tags for automatic context injection
    - Temperature and other inference parameters
    """

    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(50), unique=True, index=True)  # "coder", "planner"
    name: Mapped[str] = mapped_column(String(100))  # "Code Generator", "Task Planner"
    description: Mapped[str | None] = mapped_column(Text, nullable=True)  # Short description for UI
    system_prompt: Mapped[str] = mapped_column(Text)  # The agent's system prompt
    primary_model_id: Mapped[str] = mapped_column(
        String(100)
    )  # Default model (e.g., "claude-sonnet-4-5")
    fallback_models: Mapped[list[str]] = mapped_column(JSON, default=list)  # Ordered fallback list
    escalation_model_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # Model for complex cases
    strategies: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict
    )  # Provider-specific configs
    temperature: Mapped[float] = mapped_column(Float, default=0.7)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)  # Optimistic locking
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    versions = relationship("AgentVersion", back_populates="agent", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_agents_slug", "slug", unique=True),
        Index("ix_agents_active", "is_active"),
    )


class AgentVersion(Base):
    """Audit history for agent configuration changes.

    Tracks all changes to agent configurations for compliance and debugging.
    Each update to an Agent creates a new AgentVersion with the previous state.
    """

    __tablename__ = "agent_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(Integer, ForeignKey("agents.id", ondelete="CASCADE"))
    version: Mapped[int] = mapped_column(Integer)  # Version number at time of snapshot
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON
    )  # Full agent config at this version
    changed_by: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # User/system that made the change
    change_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # Why the change was made
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    agent = relationship("Agent", back_populates="versions")

    __table_args__ = (
        Index("ix_agent_versions_agent_id", "agent_id"),
        Index("ix_agent_versions_agent_version", "agent_id", "version"),
    )


class MemoryInjectionMetric(Base):
    """Metrics for memory context injection A/B testing.

    Tracks injection latency, counts per block, variant assignment,
    and citation tracking for optimizing JIT context injection.
    """

    __tablename__ = "memory_injection_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    session_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
    )
    external_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    project_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    # Performance metrics
    injection_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Injection counts per block
    mandates_count: Mapped[int] = mapped_column(Integer, default=0)
    guardrails_count: Mapped[int] = mapped_column(Integer, default=0)
    reference_count: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # Query context
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    # A/B variant (BASELINE, ENHANCED, MINIMAL, AGGRESSIVE)
    variant: Mapped[str] = mapped_column(String(20), default="BASELINE", index=True)
    # Outcome tracking
    task_succeeded: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    retries: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    # Citation tracking - JSON array of cited memory UUIDs
    memories_cited: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=list)
    # All memories loaded - JSON array of loaded memory UUIDs
    memories_loaded: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=list)

    # Relationships
    session = relationship("Session", back_populates="injection_metrics")

    __table_args__ = (
        Index("ix_memory_injection_metrics_created_at", "created_at"),
        Index("ix_memory_injection_metrics_external_id", "external_id"),
        Index("ix_memory_injection_metrics_variant", "variant"),
        Index("ix_memory_injection_metrics_project_id", "project_id"),
    )


class MemorySettings(Base):
    """Global memory system settings.

    Stores configuration for memory injection including token budget limits
    and enable/disable toggles. Uses singleton pattern (only one row, id=1).

    Fields:
        enabled: Kill switch for memory injection (False = no memories injected)
        budget_enabled: Budget enforcement toggle (False = inject all without limits)
        total_budget: Token budget when budget_enabled is True
    """

    __tablename__ = "memory_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)  # Singleton - always id=1
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)  # Injection kill switch
    budget_enabled: Mapped[bool] = mapped_column(Boolean, default=True)  # Budget enforcement
    total_budget: Mapped[int] = mapped_column(Integer, default=2000)  # Token budget for context
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
