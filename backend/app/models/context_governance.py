"""Immutable context changes/reviews/feedback and durable typed-screen cache."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ContextRecord(Base):
    """Append-only evidence. Changes hold complete before/after source snapshots."""
    __tablename__ = "context_records"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    actor: Mapped[str] = mapped_column(String(200))
    source_keys: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ContextJudgment(Base):
    """Semantic cache: a reserved/uncertain call is never blindly retried."""
    __tablename__ = "context_judgments"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(20))
    model_id: Mapped[str] = mapped_column(String(100))
    request: Mapped[dict[str, Any]] = mapped_column(JSON)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
