"""Configuration and settings models."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, Integer, LargeBinary, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Credential(Base):
    """Encrypted API credentials."""

    __tablename__ = "credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(100), index=True)  # claude, gemini, _system_internal
    credential_type: Mapped[str] = mapped_column(String(50))  # api_key, oauth_token, etc.
    value_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (Index("ix_credentials_provider_type", "provider", "credential_type"),)

    def __repr__(self) -> str:
        return f"<Credential id={self.id} provider={self.provider!r} type={self.credential_type!r}>"


class UserPreference(Base):
    """User preferences key-value store."""

    __tablename__ = "user_preferences"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    value: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


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
    failure_count: Mapped[int] = mapped_column(Integer, default=0)  # Consecutive failures

    __table_args__ = (Index("ix_webhook_subscriptions_project", "project_id"),)

    def __repr__(self) -> str:
        return f"<WebhookSubscription id={self.id} active={bool(self.is_active)} failures={self.failure_count}>"
