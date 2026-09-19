"""Immutable context changes/reviews/feedback and durable typed-screen cache."""
from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import JSON, DateTime, Integer, String, Text, func
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


class ContextMaintenanceItem(Base):
    """Shared revision-bound work; claims have no invented time-based expiry."""
    __tablename__ = "context_maintenance_items"
    __mapper_args__: ClassVar[dict[str, Any]] = {"eager_defaults": True}
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    kind: Mapped[str] = mapped_column(String(40))
    state: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    summary: Mapped[str] = mapped_column(Text)
    recommendation: Mapped[str] = mapped_column(Text)
    source_keys: Mapped[list[str]] = mapped_column(JSONB, default=list)
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    context: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    evidence_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    claim_owner: Mapped[str | None] = mapped_column(String(400), nullable=True)
    claim_session: Mapped[str | None] = mapped_column(String(200), nullable=True)
    decision: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    resolution: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ContextMaintenanceIngest(Base):
    __tablename__ = "context_maintenance_ingest"
    record_id: Mapped[str] = mapped_column(String(36), primary_key=True)


class ContextMaintenanceAttention(Base):
    __tablename__ = "context_maintenance_attention"
    session_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    acknowledged: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
