"""Persisted summary for the last model catalog sync run."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ModelCatalogSyncState(Base):
    """Singleton-style record storing last sync status and discovery snapshot."""

    __tablename__ = "model_catalog_sync_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(32), server_default="never")
    source_counts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    discovery_summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<ModelCatalogSyncState id={self.id} status={self.status!r} synced_at={self.synced_at}>"
