"""Subscription accounting: plan history, credit lots, usage windows and daily subscription usage.

Cash = amortized subscription fees + metered API spend + purchased credits. Calls inside included
subscription limits cost $0 marginal; their list-price value is tracked separately as API-equivalent.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class SubscriptionPlan(Base):
    """One plan period per provider. A plan change closes the open row and starts a new one."""

    __tablename__ = "subscription_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    plan: Mapped[str] = mapped_column(String(64), nullable=False)
    # NULL = price not verified; excluded from cash and flagged.
    monthly_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_subscription_plans_provider_from", "provider", "effective_from"),)


class CreditLot(Base):
    """A block of provider credits. grant = $0 cash; purchase = cash at paid_usd."""

    __tablename__ = "credit_lots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)  # grant | purchase | unclassified
    credits: Mapped[float] = mapped_column(Float, nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Reference value only for grants; for purchases paid_usd is the cash.
    value_usd_per_credit: Mapped[float | None] = mapped_column(Float, nullable=True)
    paid_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SubscriptionUsageSnapshot(Base):
    """A provider-reported usage window reading (5h / weekly), deduplicated by the collector."""

    __tablename__ = "subscription_usage_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    used_percent: Mapped[float] = mapped_column(Float, nullable=False)
    resets_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    plan_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    credits_balance: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        UniqueConstraint("provider", "window_minutes", "observed_at", name="uq_subscription_usage_snapshot"),
        Index("ix_subscription_usage_snapshots_provider_observed", "provider", "observed_at"),
    )


class SubscriptionUsageDaily(Base):
    """Daily token rollup of subscription CLI usage (Claude Code, Codex) with API-equivalent value and credits drawn."""

    __tablename__ = "subscription_usage_daily"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    model: Mapped[str] = mapped_column(String(100), primary_key=True)
    project: Mapped[str] = mapped_column(String(200), primary_key=True)
    speed: Mapped[str] = mapped_column(String(16), primary_key=True, default="standard")
    requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cached_input_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # NULL contribution when the model has no published rate; unpriced_tokens counts those tokens.
    api_equiv_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    unpriced_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # Credits actually drawn from the balance (Codex), attributed to the reporting session's project.
    credits_drawn: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class SubscriptionUsageCursor(Base):
    """Incremental read position per log file, plus collector state rows (path starting with '@')."""

    __tablename__ = "subscription_usage_cursors"

    path: Mapped[str] = mapped_column(Text, primary_key=True)
    offset: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    state: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
