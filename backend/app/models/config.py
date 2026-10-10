"""Configuration and settings models."""

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, LargeBinary, String, func
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
