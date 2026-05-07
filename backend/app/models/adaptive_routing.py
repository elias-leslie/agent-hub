"""Adaptive model routing tables."""

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
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class CapabilityDimension(Base):
    """Canonical capability or routing dimension."""

    __tablename__ = "capability_dimensions"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    value_type: Mapped[str] = mapped_column(String(20), nullable=False, server_default="score")
    direction: Mapped[str] = mapped_column(String(10), nullable=False, server_default="up")
    default_weight: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ModelCapabilityScore(Base):
    """Observed or seeded score for one model dimension."""

    __tablename__ = "model_capability_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_id: Mapped[str] = mapped_column(
        String(200), ForeignKey("models.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dimension_key: Mapped[str] = mapped_column(
        String(100), ForeignKey("capability_dimensions.key", ondelete="CASCADE"), nullable=False, index=True
    )
    numeric_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    boolean_value: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    text_value: Mapped[str | None] = mapped_column(String(200), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, server_default="0.5")
    source_type: Mapped[str] = mapped_column(String(40), nullable=False, server_default="seed")
    evidence_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    benchmark_run_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("agent_benchmark_runs.id", ondelete="SET NULL"), nullable=True
    )
    measured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_model_capability_model_dimension", "model_id", "dimension_key"),
    )


class WorkloadProfile(Base):
    """Reusable workload requirement profile."""

    __tablename__ = "workload_profiles"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    requirement_deltas: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    hard_constraints: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    risk_tier: Mapped[str] = mapped_column(String(20), nullable=False, server_default="normal")
    verifier_policy: Mapped[str] = mapped_column(String(40), nullable=False, server_default="optional")
    default_routing_mode: Mapped[str] = mapped_column(String(20), nullable=False, server_default="auto_shadow")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentRoutingProfile(Base):
    """Default routing policy for one exact agent."""

    __tablename__ = "agent_routing_profiles"

    agent_slug: Mapped[str] = mapped_column(
        String(100), ForeignKey("agents.slug", ondelete="CASCADE"), primary_key=True
    )
    default_routing_mode: Mapped[str] = mapped_column(String(20), nullable=False, server_default="auto_shadow")
    risk_tier: Mapped[str] = mapped_column(String(20), nullable=False, server_default="normal")
    cost_policy: Mapped[str] = mapped_column(String(40), nullable=False, server_default="subscription_first")
    subscription_policy: Mapped[str] = mapped_column(String(40), nullable=False, server_default="prefer_subscription")
    exploration_policy: Mapped[str] = mapped_column(String(40), nullable=False, server_default="shadow_only")
    quality_floor: Mapped[float | None] = mapped_column(Float, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (Index("ix_agent_routing_profiles_mode", "default_routing_mode"),)


class AgentWorkloadRoutingMode(Base):
    """Routing mode override for agent + workload."""

    __tablename__ = "agent_workload_routing_modes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_slug: Mapped[str] = mapped_column(
        String(100), ForeignKey("agents.slug", ondelete="CASCADE"), nullable=False, index=True
    )
    workload_profile: Mapped[str] = mapped_column(
        String(100), ForeignKey("workload_profiles.key", ondelete="CASCADE"), nullable=False, index=True
    )
    routing_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    canary_percent: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner: Mapped[str | None] = mapped_column(String(100), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("agent_slug", "workload_profile", name="uq_agent_workload_routing_mode"),
    )


class ManualModelRoute(Base):
    """Manual model chain for an agent, optionally scoped to workload."""

    __tablename__ = "manual_model_routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_slug: Mapped[str] = mapped_column(
        String(100), ForeignKey("agents.slug", ondelete="CASCADE"), nullable=False, index=True
    )
    workload_profile: Mapped[str | None] = mapped_column(
        String(100), ForeignKey("workload_profiles.key", ondelete="SET NULL"), nullable=True, index=True
    )
    primary_model_id: Mapped[str] = mapped_column(
        String(200), ForeignKey("models.id", ondelete="RESTRICT"), nullable=False
    )
    fallback_models: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    escalation_model_id: Mapped[str | None] = mapped_column(
        String(200), ForeignKey("models.id", ondelete="RESTRICT"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner: Mapped[str | None] = mapped_column(String(100), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    allow_health_fallback: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_manual_model_routes_agent_workload", "agent_slug", "workload_profile", "enabled"),
    )


class ProviderEntitlement(Base):
    """Provider/subscription/API/local entitlement status."""

    __tablename__ = "provider_entitlements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    auth_mode: Mapped[str] = mapped_column(String(40), nullable=False)
    plan: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="unknown")
    quota_units: Mapped[float | None] = mapped_column(Float, nullable=True)
    quota_window: Mapped[str | None] = mapped_column(String(40), nullable=True)
    auth_secret_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    discovery_source: Mapped[str | None] = mapped_column(String(100), nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, server_default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_provider_entitlements_provider_status", "provider", "status", "enabled"),
    )


class ModelAvailability(Base):
    """Whether a catalog/discovered model is available and safe to route."""

    __tablename__ = "model_availability"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_id: Mapped[str] = mapped_column(
        String(200), ForeignKey("models.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entitlement_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("provider_entitlements.id", ondelete="SET NULL"), nullable=True
    )
    discovered_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    routable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    last_smoke_status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="not_run")
    last_smoke_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    capabilities_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("model_id", "provider", name="uq_model_availability_model_provider"),
        Index("ix_model_availability_routable", "routable", "enabled"),
    )


class RoutingPolicyVersion(Base):
    """Versioned routing policy weights/configuration."""

    __tablename__ = "routing_policy_versions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid())
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    policy: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false", index=True)
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RoutingDecision(Base):
    """One route decision, including shadow decisions."""

    __tablename__ = "routing_decisions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, server_default=func.gen_random_uuid())
    request_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    session_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    agent_slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    workload_profile: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    routing_mode: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    input_features: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default="[]")
    chosen_model_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    chosen_provider: Mapped[str] = mapped_column(String(100), nullable=False)
    fallback_chain: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default="[]")
    score_breakdown: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    policy_version_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("routing_policy_versions.id", ondelete="SET NULL"), nullable=True
    )
    constraints_hit: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    fallback_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    manual_route_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("manual_model_routes.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="selected", index=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_routing_decisions_agent_workload_created", "agent_slug", "workload_profile", "created_at"),
    )


class ModelWorkloadPerformance(Base):
    """Rolling model score for one workload/agent scope."""

    __tablename__ = "model_workload_performance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_slug: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    workload_profile: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    model_id: Mapped[str] = mapped_column(
        String(200), ForeignKey("models.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rolling_score: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    pass_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    verifier_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    strict_json_pass_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    fallback_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    timeout_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    p50_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    p95_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_model_workload_perf_lookup", "workload_profile", "agent_slug", "model_id"),
    )
