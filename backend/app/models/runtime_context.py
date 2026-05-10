"""Runtime context profile overrides for external agentic CLIs."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class RuntimeContextProfilePolicy(Base):
    """Per-profile injection caps for mandates / guardrails / references.

    NULL on any limit column means uncapped; integers cap inclusively.
    Per-agent memory_config overrides take precedence over these defaults.
    """

    __tablename__ = "runtime_context_profile_policies"

    consumer_profile: Mapped[str] = mapped_column(String(64), primary_key=True)
    mandate_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    guardrail_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reference_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


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
    # User-forced render tier for this memory in this profile/project.
    # NULL = no tier override; values: 'L0', 'L1', 'L2'.
    tier_override: Mapped[str | None] = mapped_column(String(8), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="50")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
