"""Durable budget and dispatch records for the bounded TypeSafe Jev pilot."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class TypeSafeJevBudget(Base):
    """Single hard ceiling shared by every request in one named Jev pilot."""

    __tablename__ = "typesafe_jev_budgets"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    ceiling_usd: Mapped[Decimal] = mapped_column(Numeric(12, 9), nullable=False)
    spent_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 9), nullable=False, server_default="0"
    )
    reserved_usd: Mapped[Decimal] = mapped_column(
        Numeric(12, 9), nullable=False, server_default="0"
    )
    model_id: Mapped[str] = mapped_column(String(100), nullable=False)
    pricing_contract: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class TypeSafeJevDispatch(Base):
    """One immutable request identity plus its reservation and observed outcome."""

    __tablename__ = "typesafe_jev_dispatches"

    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    budget_key: Mapped[str] = mapped_column(
        ForeignKey("typesafe_jev_budgets.key"), nullable=False, index=True
    )
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    model_requested: Mapped[str] = mapped_column(String(100), nullable=False)
    model_observed: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pricing_contract: Mapped[str] = mapped_column(String(200), nullable=False)
    reserved_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 9), nullable=False)
    actual_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 9), nullable=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_provenance: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    rubric_provenance: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    observation_provenance: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    answers: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    error_kind: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_typesafe_jev_dispatches_budget_status", "budget_key", "status"),
    )
