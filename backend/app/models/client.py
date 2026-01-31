"""Client authentication and access control models."""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


def check_project_access(allowed_projects: str | None, project_id: str) -> bool:
    """Check if a project_id is allowed for a client.

    Args:
        allowed_projects: JSON array of allowed project_ids, or None for unrestricted
        project_id: The project_id to check

    Returns:
        True if access is allowed, False otherwise
    """
    if allowed_projects is None:
        return True  # Unrestricted (internal clients)
    try:
        projects = json.loads(allowed_projects)
        if not isinstance(projects, list):
            return False
        return project_id in projects
    except (json.JSONDecodeError, TypeError):
        return False


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
    # Project access control
    allowed_projects: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # JSON array of allowed project_ids, null = unrestricted (internal clients)

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
