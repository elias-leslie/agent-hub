"""Canonical model catalog tables."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ModelCatalogEntry(Base):
    """Canonical DB-backed model catalog row."""

    __tablename__ = "models"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    alias: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    hint: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    provider: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    score_coding: Mapped[int] = mapped_column(Integer, nullable=False)
    score_reasoning: Mapped[int] = mapped_column(Integer, nullable=False)
    score_planning: Mapped[int] = mapped_column(Integer, nullable=False)
    score_tool_use: Mapped[int] = mapped_column(Integer, nullable=False)
    score_instruction: Mapped[int] = mapped_column(Integer, nullable=False)
    score_design: Mapped[int] = mapped_column(Integer, nullable=False)

    cost_input_per_m: Mapped[float] = mapped_column(Float, nullable=False)
    cost_output_per_m: Mapped[float] = mapped_column(Float, nullable=False)
    pricing_unit: Mapped[str] = mapped_column(String(50), nullable=False, server_default="per_million_tokens")
    unit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    service_tiers: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    cache_read_per_million: Mapped[float | None] = mapped_column(Float, nullable=True)
    cache_write_per_million: Mapped[float | None] = mapped_column(Float, nullable=True)

    context_window: Mapped[int] = mapped_column(Integer, nullable=False)
    speed_tier: Mapped[str] = mapped_column(String(20), nullable=False)

    can_generate_images: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    has_vision: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    can_edit_images: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    has_thinking: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    supports_pdf: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    supports_audio: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    supports_tool_execution: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    supports_verbosity: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    supports_xhigh: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    supports_session_cache: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    max_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)

    release_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    knowledge_cutoff: Mapped[str | None] = mapped_column(String(40), nullable=True)
    family: Mapped[str | None] = mapped_column(String(100), nullable=True)
    availability: Mapped[str | None] = mapped_column(String(200), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    source: Mapped[str] = mapped_column(String(50), nullable=False, server_default="seed")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_models_provider_active", "provider", "is_active"),
        Index("ix_models_sort_order", "sort_order"),
    )

    def __repr__(self) -> str:
        return f"<ModelCatalogEntry id={self.id!r} provider={self.provider!r}>"


class ModelAlias(Base):
    """Alias row resolving user-facing names to canonical model IDs."""

    __tablename__ = "model_aliases"

    alias: Mapped[str] = mapped_column(String(200), primary_key=True)
    model_id: Mapped[str] = mapped_column(
        String(200),
        ForeignKey("models.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    alias_type: Mapped[str] = mapped_column(String(50), nullable=False, server_default="manual")
    source: Mapped[str] = mapped_column(String(50), nullable=False, server_default="seed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<ModelAlias alias={self.alias!r} model_id={self.model_id!r}>"
