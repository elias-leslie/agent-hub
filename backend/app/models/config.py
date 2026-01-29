"""Configuration and settings models."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, Index, Integer, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.constants import DEFAULT_CLAUDE_MODEL

from .base import Base


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
