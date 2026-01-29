"""Memory system models for context injection and tracking."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class MemoryInjectionMetric(Base):
    """Metrics for memory context injection A/B testing.

    Tracks injection latency, counts per block, variant assignment,
    and citation tracking for optimizing JIT context injection.
    """

    __tablename__ = "memory_injection_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    session_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("sessions.id", ondelete="SET NULL"), nullable=True
    )
    external_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    project_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    # Performance metrics
    injection_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Injection counts per block
    mandates_count: Mapped[int] = mapped_column(Integer, default=0)
    guardrails_count: Mapped[int] = mapped_column(Integer, default=0)
    reference_count: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # Query context
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    # A/B variant (BASELINE, ENHANCED, MINIMAL, AGGRESSIVE)
    variant: Mapped[str] = mapped_column(String(20), default="BASELINE", index=True)
    # Outcome tracking
    task_succeeded: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    retries: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    # Citation tracking - JSON array of cited memory UUIDs
    memories_cited: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=list)
    # All memories loaded - JSON array of loaded memory UUIDs
    memories_loaded: Mapped[list[str] | None] = mapped_column(JSON, nullable=True, default=list)

    # Relationships
    session = relationship("Session", back_populates="injection_metrics")

    __table_args__ = (
        Index("ix_memory_injection_metrics_created_at", "created_at"),
        Index("ix_memory_injection_metrics_external_id", "external_id"),
        Index("ix_memory_injection_metrics_variant", "variant"),
        Index("ix_memory_injection_metrics_project_id", "project_id"),
    )


class MemorySettings(Base):
    """Global memory system settings.

    Stores configuration for memory injection including token budget limits
    and enable/disable toggles. Uses singleton pattern (only one row, id=1).

    Fields:
        enabled: Kill switch for memory injection (False = no memories injected)
        budget_enabled: Budget enforcement toggle (False = inject all without limits)
        total_budget: Token budget when budget_enabled is True
    """

    __tablename__ = "memory_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)  # Singleton - always id=1
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)  # Injection kill switch
    budget_enabled: Mapped[bool] = mapped_column(Boolean, default=True)  # Budget enforcement
    total_budget: Mapped[int] = mapped_column(Integer, default=2000)  # Token budget for context
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UsageStatLog(Base):
    """Historical usage statistics for memory episodes.

    Tracks when golden standards and other memory entries are:
    - loaded: Injected into context
    - referenced: Cited by LLM in response
    - success: Associated with positive feedback
    """

    __tablename__ = "usage_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    episode_uuid: Mapped[str] = mapped_column(String(36), index=True)
    metric_type: Mapped[str] = mapped_column(
        Enum("loaded", "referenced", "success", name="usage_metric_type"),
    )
    value: Mapped[int] = mapped_column(Integer, default=1)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_usage_stats_timestamp", "timestamp"),
        Index("ix_usage_stats_episode_metric", "episode_uuid", "metric_type"),
    )
