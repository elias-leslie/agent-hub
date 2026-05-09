"""Runtime context profile overrides for external agentic CLIs."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class RuntimeContextOverride(Base):
    """Human override for runtime context selection and ordering."""

    __tablename__ = "runtime_context_overrides"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid()
    )
    consumer_profile: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_id: Mapped[str] = mapped_column(String(120), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, server_default="include")
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="50")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
