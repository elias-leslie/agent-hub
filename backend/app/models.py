"""
SQLAlchemy models for Agent Hub.

Tables:
- sessions: AI conversation sessions
- messages: Individual messages within sessions
- credentials: Encrypted API credentials
- cost_logs: Token usage and cost tracking
"""

from sqlalchemy import (
    JSON,
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
    func,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


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
    # Provider-specific metadata (SDK session IDs, cache info, etc.)
    provider_metadata = Column(JSON, nullable=True, default=dict)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    messages = relationship("Message", back_populates="session", cascade="all, delete-orphan")
    cost_logs = relationship("CostLog", back_populates="session", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_sessions_project_created", "project_id", "created_at"),)


class Message(Base):
    """Individual message within a session."""

    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)
    tokens = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)

    # Relationships
    session = relationship("Session", back_populates="messages")

    __table_args__ = (Index("ix_messages_session_created", "session_id", "created_at"),)


class Credential(Base):
    """Encrypted API credentials."""

    __tablename__ = "credentials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    provider = Column(String(20), nullable=False, index=True)  # claude, gemini
    credential_type = Column(String(50), nullable=False)  # api_key, oauth_token, etc.
    value_encrypted = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)

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
    created_at = Column(DateTime, default=func.now(), nullable=False)

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
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    expires_at = Column(DateTime, nullable=True)  # Optional expiration

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
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
    last_triggered_at = Column(DateTime, nullable=True)
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
    created_at = Column(DateTime, default=func.now(), nullable=False)

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
    default_model = Column(String(100), default="claude-sonnet-4-5", nullable=False)
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)


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
    created_at = Column(DateTime, default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_truncation_events_model_created", "model", "created_at"),
        Index("ix_truncation_events_created", "created_at"),
    )
