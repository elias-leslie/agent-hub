"""Persistent benchmark history for agent evaluation and regression tracking."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class AgentBenchmarkRun(Base):
    """One persisted benchmark or honing iteration run."""

    __tablename__ = "agent_benchmark_runs"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid()
    )
    benchmark_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    agent_slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    suite_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    run_kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="completed")

    models: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    case_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    runs_per_case: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    use_memory: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)

    avg_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    pass_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    passed_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    infra_failure_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    config_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    run_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    attempts = relationship(
        "AgentBenchmarkAttempt",
        back_populates="benchmark_run",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    __table_args__ = (
        Index("ix_agent_benchmark_runs_agent_suite_completed", "agent_slug", "suite_id", "completed_at"),
    )


class AgentBenchmarkAttempt(Base):
    """One scored benchmark attempt inside a persisted run."""

    __tablename__ = "agent_benchmark_attempts"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid()
    )
    benchmark_run_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("agent_benchmark_runs.id", ondelete="CASCADE"), nullable=False
    )
    agent_slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    model_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    effective_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    requested_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    case_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    run_number: Mapped[int] = mapped_column(Integer, nullable=False)
    session_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True)

    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    turns: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    tool_calls_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    used_tool_names: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")

    schema_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    tool_requirement_met: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    correctness_score: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    composite_score: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    infra_failure: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    failure_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    failure_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    primary_action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    should_dispatch: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    should_close: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(16), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_content: Mapped[str] = mapped_column(Text, nullable=False, server_default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    benchmark_run = relationship("AgentBenchmarkRun", back_populates="attempts", lazy="raise")

    __table_args__ = (
        Index("ix_agent_benchmark_attempts_run_case", "benchmark_run_id", "case_id"),
        Index("ix_agent_benchmark_attempts_agent_model_created", "agent_slug", "model_id", "created_at"),
    )


class AgentRegressionCluster(Base):
    """Tracks recurring benchmark regressions until they are resolved."""

    __tablename__ = "agent_regression_clusters"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid()
    )
    agent_slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    suite_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    regression_key: Mapped[str] = mapped_column(String(255), nullable=False)
    case_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    failure_detail: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="open", index=True)
    first_seen_run_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("agent_benchmark_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_seen_run_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("agent_benchmark_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    latest_avg_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    affected_models: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    cluster_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "agent_slug",
            "suite_id",
            "regression_key",
            name="uq_agent_regression_clusters_agent_suite_key",
        ),
        Index("ix_agent_regression_clusters_agent_suite_status", "agent_slug", "suite_id", "status"),
    )
