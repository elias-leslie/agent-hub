"""
SQLAlchemy models for Agent Hub.

Tables:
- sessions: AI conversation sessions
- messages: Individual messages within sessions
- credentials: Encrypted API credentials
- cost_logs: Token usage and cost tracking
- llm_models: LLM model registry (centralized model definitions)
"""

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, relationship

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

    id = Column(String(36), primary_key=True)  # UUID
    display_name = Column(String(100), nullable=False)
    client_type = Column(
        Enum("internal", "external", "service", name="client_type_enum"),
        nullable=False,
        default="external",
    )
    secret_hash = Column(String(128), nullable=False)  # bcrypt hash
    secret_prefix = Column(String(20), nullable=False)  # "ahc_" + first 8 chars for display
    status = Column(
        Enum("active", "suspended", "blocked", name="client_status_enum"),
        nullable=False,
        default="active",
    )
    # Rate limiting
    rate_limit_rpm = Column(Integer, nullable=False, default=60)  # Requests per minute
    rate_limit_tpm = Column(Integer, nullable=False, default=100000)  # Tokens per minute
    # Audit fields
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    suspended_at = Column(DateTime(timezone=True), nullable=True)
    suspended_by = Column(String(100), nullable=True)
    suspension_reason = Column(Text, nullable=True)

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

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(String(36), ForeignKey("clients.id", ondelete="SET NULL"), nullable=True)
    request_source = Column(String(100), nullable=True)  # From X-Request-Source header
    endpoint = Column(String(200), nullable=False)
    method = Column(String(10), nullable=False)  # GET, POST, etc.
    status_code = Column(Integer, nullable=False)
    rejection_reason = Column(
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
    tokens_in = Column(Integer, nullable=True)
    tokens_out = Column(Integer, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    # Request context
    model = Column(String(100), nullable=True)
    session_id = Column(String(36), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    client = relationship("Client", back_populates="request_logs")

    __table_args__ = (
        Index("ix_request_logs_client_id", "client_id"),
        Index("ix_request_logs_created_at", "created_at"),
        Index("ix_request_logs_status_code", "status_code"),
        Index("ix_request_logs_client_created", "client_id", "created_at"),
    )


class Session(Base):
    """AI conversation session."""

    __tablename__ = "sessions"

    id = Column(String(36), primary_key=True)
    project_id = Column(String(100), nullable=False, index=True)
    provider = Column(String(20), nullable=False)  # claude, gemini
    model = Column(String(100), nullable=False)
    status = Column(
        Enum("active", "completed", "failed", name="session_status"),
        default="active",
        nullable=False,
    )
    # Purpose describes why this session was created (task_enrichment, code_generation, etc.)
    purpose = Column(String(100), nullable=True, index=True)
    # External ID for caller-defined cost aggregation (e.g., task ID, user ID, billing entity)
    external_id = Column(String(100), nullable=True, index=True)
    # Session type for categorizing workflows
    session_type = Column(
        Enum(
            "completion",
            "chat",
            "roundtable",
            "image_generation",
            "agent",  # Long-running automated agent sessions (24h idle timeout)
            name="session_type_enum",
        ),
        default="completion",
        nullable=False,
    )
    # Access control - who made this request
    client_id = Column(String(36), ForeignKey("clients.id", ondelete="SET NULL"), nullable=True)
    request_source = Column(String(100), nullable=True)  # From X-Request-Source header
    # Legacy session flag - True for sessions created before access control was implemented
    is_legacy = Column(Boolean, default=False, nullable=False, index=True)
    # Provider-specific metadata (SDK session IDs, cache info, etc.)
    provider_metadata = Column(JSON, nullable=True, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
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

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)
    tokens = Column(Integer, nullable=True)
    # Agent identifier for multi-agent sessions (roundtable, orchestration)
    agent_id = Column(String(100), nullable=True, index=True)
    # Agent display name for UI
    agent_name = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    session = relationship("Session", back_populates="messages")

    __table_args__ = (
        Index("ix_messages_session_created", "session_id", "created_at"),
        Index("ix_messages_session_agent", "session_id", "agent_id"),
    )


class Credential(Base):
    """Encrypted API credentials."""

    __tablename__ = "credentials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String(20), nullable=False, index=True)  # claude, gemini
    credential_type = Column(String(50), nullable=False)  # api_key, oauth_token, etc.
    value_encrypted = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_credentials_provider_type", "provider", "credential_type"),)


class CostLog(Base):
    """Token usage and cost tracking per request."""

    __tablename__ = "cost_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    model = Column(String(100), nullable=False)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    cost_usd = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    session = relationship("Session", back_populates="cost_logs")

    __table_args__ = (
        Index("ix_cost_logs_session", "session_id"),
        Index("ix_cost_logs_created", "created_at"),
    )


class APIKey(Base):
    """Virtual API keys for OpenAI-compatible endpoint authentication."""

    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key_hash = Column(String(64), nullable=False, unique=True, index=True)  # SHA-256 hash
    key_prefix = Column(String(20), nullable=False)  # "sk-ah-" + first 8 chars for display
    name = Column(String(100), nullable=True)  # User-friendly name
    project_id = Column(String(100), nullable=False, index=True)  # For cost tracking
    rate_limit_rpm = Column(Integer, nullable=False, default=60)  # Requests per minute
    rate_limit_tpm = Column(Integer, nullable=False, default=100000)  # Tokens per minute
    is_active = Column(Integer, nullable=False, default=1)  # 1=active, 0=revoked
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=True)  # Optional expiration

    __table_args__ = (Index("ix_api_keys_project", "project_id"),)


class WebhookSubscription(Base):
    """Webhook subscriptions for session event notifications."""

    __tablename__ = "webhook_subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(String(2048), nullable=False)  # Callback URL
    secret = Column(String(64), nullable=False)  # HMAC secret for signature verification
    event_types = Column(JSON, nullable=False)  # List of event types to receive
    project_id = Column(String(100), nullable=True, index=True)  # Filter to specific project
    is_active = Column(Integer, nullable=False, default=1)  # 1=active, 0=disabled
    description = Column(String(255), nullable=True)  # User-friendly description
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    last_triggered_at = Column(DateTime(timezone=True), nullable=True)
    failure_count = Column(Integer, nullable=False, default=0)  # Consecutive failures

    __table_args__ = (Index("ix_webhook_subscriptions_project", "project_id"),)


class MessageFeedback(Base):
    """User feedback on AI message responses."""

    __tablename__ = "message_feedback"

    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(String(100), nullable=False, index=True)  # Client-side message ID
    session_id = Column(String(36), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True)
    feedback_type = Column(
        Enum("positive", "negative", name="feedback_type"),
        nullable=False,
    )
    category = Column(
        String(50), nullable=True
    )  # incorrect, unhelpful, incomplete, offensive, other
    details = Column(Text, nullable=True)  # User-provided text feedback
    # Memory rule UUIDs that were active when feedback was given (for attribution)
    referenced_rule_uuids = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_message_feedback_message", "message_id"),
        Index("ix_message_feedback_session", "session_id"),
        Index("ix_message_feedback_type", "feedback_type"),
    )


class UserPreferences(Base):
    """User preferences for AI interactions."""

    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        String(100), nullable=False, unique=True, index=True
    )  # Identifier for the user
    verbosity = Column(
        Enum("concise", "normal", "detailed", name="verbosity_level"),
        default="normal",
        nullable=False,
    )
    tone = Column(
        Enum("professional", "friendly", "technical", name="tone_type"),
        default="professional",
        nullable=False,
    )
    default_model = Column(String(100), default=DEFAULT_CLAUDE_MODEL, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TruncationEvent(Base):
    """Telemetry for response truncations (output limit events)."""

    __tablename__ = "truncation_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True)
    model = Column(String(100), nullable=False, index=True)
    endpoint = Column(String(50), nullable=False)  # "complete", "stream"
    max_tokens_requested = Column(Integer, nullable=False)
    output_tokens = Column(Integer, nullable=False)
    model_limit = Column(Integer, nullable=False)
    was_capped = Column(
        Integer, nullable=False, default=0
    )  # 1 if request was capped to model limit
    project_id = Column(String(100), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_truncation_events_model_created", "model", "created_at"),
        Index("ix_truncation_events_created", "created_at"),
    )


class RoundtableSession(Base):
    """Roundtable multi-agent collaboration session."""

    __tablename__ = "roundtable_sessions"

    id = Column(String(36), primary_key=True)
    project_id = Column(String(100), nullable=False, index=True)
    mode = Column(
        Enum("quick", "deliberation", name="roundtable_mode"),
        default="quick",
        nullable=False,
    )
    tool_mode = Column(
        Enum("read_only", "yolo", name="roundtable_tool_mode"),
        default="read_only",
        nullable=False,
    )
    status = Column(
        Enum("active", "completed", "failed", name="roundtable_status"),
        default="active",
        nullable=False,
    )
    memory_group_id = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    messages = relationship(
        "RoundtableMessage", back_populates="session", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_roundtable_sessions_project_created", "project_id", "created_at"),)


class RoundtableMessage(Base):
    """Individual message in a roundtable session."""

    __tablename__ = "roundtable_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(
        String(36), ForeignKey("roundtable_sessions.id", ondelete="CASCADE"), nullable=False
    )
    role = Column(String(20), nullable=False)  # user, assistant, system
    agent_type = Column(String(20), nullable=True)  # claude, gemini (null for user/system)
    content = Column(Text, nullable=False)
    tokens = Column(Integer, nullable=True)
    model = Column(String(100), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

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

    id = Column(Integer, primary_key=True, autoincrement=True)
    episode_uuid = Column(String(36), nullable=False, index=True)
    metric_type = Column(
        Enum("loaded", "referenced", "success", name="usage_metric_type"),
        nullable=False,
    )
    value = Column(Integer, nullable=False, default=1)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

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

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_name = Column(String(100), nullable=False, unique=True, index=True)
    enabled = Column(Boolean, nullable=False, default=True)
    disabled_at = Column(DateTime(timezone=True), nullable=True)
    disabled_by = Column(String(100), nullable=True)  # User/admin who disabled
    reason = Column(Text, nullable=True)  # Reason for disabling
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PurposeControl(Base):
    """Kill switch control for request purposes.

    Used to enable/disable API access for specific purposes.
    When disabled=True, requests with this purpose are blocked with 403.
    """

    __tablename__ = "purpose_controls"

    id = Column(Integer, primary_key=True, autoincrement=True)
    purpose = Column(String(100), nullable=False, unique=True, index=True)
    enabled = Column(Boolean, nullable=False, default=True)
    disabled_at = Column(DateTime(timezone=True), nullable=True)
    disabled_by = Column(String(100), nullable=True)  # User/admin who disabled
    reason = Column(Text, nullable=True)  # Reason for disabling
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ClientPurposeControl(Base):
    """Kill switch control for specific client+purpose combinations.

    Provides granular control: block a specific client from a specific purpose
    without blocking either globally. Checked hierarchically:
    1. Check ClientPurposeControl (client, purpose)
    2. Check ClientControl (client)
    3. Check PurposeControl (purpose)
    """

    __tablename__ = "client_purpose_controls"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_name = Column(String(100), nullable=False, index=True)
    purpose = Column(String(100), nullable=False, index=True)
    enabled = Column(Boolean, nullable=False, default=True)
    disabled_at = Column(DateTime(timezone=True), nullable=True)
    disabled_by = Column(String(100), nullable=True)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("client_name", "purpose", name="uq_client_purpose"),
        Index("ix_client_purpose_controls_combo", "client_name", "purpose"),
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

    id = Column(Integer, primary_key=True, autoincrement=True)
    slug = Column(String(50), nullable=False, unique=True, index=True)  # "coder", "planner"
    name = Column(String(100), nullable=False)  # "Code Generator", "Task Planner"
    description = Column(Text, nullable=True)  # Short description for UI
    system_prompt = Column(Text, nullable=False)  # The agent's system prompt
    primary_model_id = Column(
        String(100), nullable=False
    )  # Default model (e.g., "claude-sonnet-4-5")
    fallback_models = Column(JSON, nullable=False, default=list)  # Ordered fallback list
    escalation_model_id = Column(String(100), nullable=True)  # Model for complex cases
    strategies = Column(JSON, nullable=False, default=dict)  # Provider-specific configs
    temperature = Column(Float, nullable=False, default=0.7)
    max_tokens = Column(Integer, nullable=True)  # Default max_tokens (None = model default)
    is_active = Column(Boolean, nullable=False, default=True)
    version = Column(Integer, nullable=False, default=1)  # Optimistic locking
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
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

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(Integer, ForeignKey("agents.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False)  # Version number at time of snapshot
    config_snapshot = Column(JSON, nullable=False)  # Full agent config at this version
    changed_by = Column(String(100), nullable=True)  # User/system that made the change
    change_reason = Column(Text, nullable=True)  # Why the change was made
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

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

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    session_id = Column(String(36), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True)
    external_id = Column(String(100), nullable=True, index=True)
    project_id = Column(String(100), nullable=True, index=True)
    # Performance metrics
    injection_latency_ms = Column(Integer, nullable=True)
    # Injection counts per block
    mandates_count = Column(Integer, nullable=False, default=0)
    guardrails_count = Column(Integer, nullable=False, default=0)
    reference_count = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    # Query context
    query = Column(Text, nullable=True)
    # A/B variant (BASELINE, ENHANCED, MINIMAL, AGGRESSIVE)
    variant = Column(String(20), nullable=False, default="BASELINE", index=True)
    # Outcome tracking
    task_succeeded = Column(Boolean, nullable=True)
    retries = Column(Integer, nullable=True, default=0)
    # Citation tracking - JSON array of cited memory UUIDs
    memories_cited = Column(JSON, nullable=True, default=list)
    # All memories loaded - JSON array of loaded memory UUIDs
    memories_loaded = Column(JSON, nullable=True, default=list)

    # Relationships
    session = relationship("Session", back_populates="injection_metrics")

    __table_args__ = (
        Index("ix_memory_injection_metrics_created_at", "created_at"),
        Index("ix_memory_injection_metrics_external_id", "external_id"),
        Index("ix_memory_injection_metrics_variant", "variant"),
        Index("ix_memory_injection_metrics_project_id", "project_id"),
    )
