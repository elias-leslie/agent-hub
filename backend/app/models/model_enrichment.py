"""Model enrichment — external benchmark data overlay on DB model catalog."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ModelEnrichment(Base):
    """Stores external benchmark/pricing data as an overlay on models.

    Each row corresponds to a model_id in the DB-backed catalog and stores
    enrichment data fetched from external sources (models.dev, benchmarks.json).
    """

    __tablename__ = "model_enrichments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_id: Mapped[str] = mapped_column(String(200), unique=True, index=True)

    # External benchmark scores (override/supplement catalog scores)
    ext_coding: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ext_reasoning: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ext_tool_use: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ext_planning: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ext_instruction: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ext_speed_tier: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ext_input_per_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    ext_output_per_m: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Raw external data for reference
    raw_benchmark_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Provenance
    source: Mapped[str] = mapped_column(String(100), server_default="models.dev")
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_model_enrichments_synced_at", "synced_at"),
    )

    def __repr__(self) -> str:
        return f"<ModelEnrichment model_id={self.model_id!r} synced_at={self.synced_at}>"
