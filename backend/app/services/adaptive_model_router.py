"""DB-backed adaptive model routing."""

from __future__ import annotations

import hashlib
import logging
import shutil
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.catalog import resolve_model
from app.models import (
    Agent,
    AgentRoutingProfile,
    AgentWorkloadRoutingMode,
    CapabilityDimension,
    ManualModelRoute,
    ModelAvailability,
    ModelCapabilityScore,
    ModelCatalogEntry,
    ModelWorkloadPerformance,
    ProviderEntitlement,
    RoutingDecision,
    WorkloadProfile,
)
from app.routing.registry import get_provider_for_model
from app.services.agent_dto import AgentDTO
from app.services.credential_manager import get_credential_manager

logger = logging.getLogger(__name__)

RoutingMode = Literal["manual_locked", "auto_shadow", "auto_canary", "auto"]

ROUTING_MODES: set[str] = {"manual_locked", "auto_shadow", "auto_canary", "auto"}
SYSTEM_DEFAULT_MODE: RoutingMode = "auto"
PROFILE_METADATA_SOURCE = "auto-routing-enable-v1"
MANAGED_PROFILE_SOURCES = {"migration", "startup_seed"}

PROVIDER_ROUTING_METADATA: dict[str, dict[str, Any]] = {
    "claude": {
        "subscription_first": True,
        "routine_auto_penalty": 2.0,
        "notes": "Use Claude subscription for strong fit, but reserve Opus-heavy work for protected/escalation paths.",
    },
    "codex": {
        "subscription_first": True,
        "routine_auto_penalty": 8.0,
        "notes": "Reserve Codex subscription for protected, verification, escalation, or explicit quality-biased routing.",
    },
    "kimi-code": {
        "subscription_first": True,
        "coding_auto_bonus": 4.0,
        "code_review_auto_bonus": 2.0,
        "noncoding_auto_penalty": 5.0,
        "notes": "Preferred routine coding subscription path while Codex quota is conserved.",
    },
    "minimax": {
        "subscription_first": True,
        "routine_auto_bonus": 2.0,
        "planning_auto_bonus": 4.0,
        "reasoning_auto_bonus": 2.0,
        "prompt_auto_bonus": 2.0,
        "notes": "Preferred routine planning/reasoning subscription path when fit is close.",
    },
    "gemini": {
        "subscription_first": False,
        "routine_auto_bonus": 1.0,
        "utility_auto_bonus": 8.0,
        "vision_auto_bonus": 3.0,
        "notes": "Useful low-cost/free-tier utility path.",
    },
}

CRITICAL_AGENT_SLUGS = {
    "bear-researcher-v1",
    "bull-researcher-v1",
    "persona",
    "verifier",
    "equity-analyst",
    "financial-document-reviewer",
    "fundamentals-v1",
    "governance-auditor",
    "investment-committee",
    "market-pulse-analyst",
    "market-pulse-scout",
    "news-grounded-v1",
    "portfolio-mgr-v1",
    "risk-aggressive-v1",
    "risk-conservative-v1",
    "risk-manager",
    "risk-neutral-v1",
    "sentiment-grounded-v1",
    "technical-v1",
    "trade-manager",
    "trader-v1",
}
FINANCE_AGENT_SLUGS = {
    "bear-researcher-v1",
    "bull-researcher-v1",
    "equity-analyst",
    "financial-document-reviewer",
    "fundamentals-v1",
    "investment-committee",
    "market-pulse-analyst",
    "market-pulse-scout",
    "news-grounded-v1",
    "portfolio-mgr-v1",
    "risk-aggressive-v1",
    "risk-conservative-v1",
    "risk-manager",
    "risk-neutral-v1",
    "sentiment-grounded-v1",
    "technical-v1",
    "trade-manager",
    "trader-v1",
}
UTILITY_AGENT_SLUGS = {
    "context-compactor",
    "learning-extractor",
    "memory-rater",
    "note-formatter",
    "note-titler",
    "summarizer",
}

LOW_RISK_CANARY_OVERRIDES: tuple[tuple[str, str, float], ...] = ()

DIMENSION_SEEDS: tuple[tuple[str, str, str, str, str, float], ...] = (
    ("coding", "Coding", "quality", "score", "up", 0.20),
    ("swe_agentic", "SWE Agentic", "quality", "score", "up", 0.16),
    ("code_review", "Code Review", "quality", "score", "up", 0.14),
    ("planning_orchestration", "Planning/Orchestration", "quality", "score", "up", 0.16),
    ("reasoning", "Reasoning", "quality", "score", "up", 0.16),
    ("tool_use", "Tool Use", "quality", "score", "up", 0.14),
    ("instruction", "Instruction Following", "quality", "score", "up", 0.12),
    ("strict_json", "Strict JSON", "quality", "score", "up", 0.12),
    ("math", "Math", "quality", "score", "up", 0.10),
    ("data_analysis", "Data Analysis", "quality", "score", "up", 0.12),
    ("data_research", "Data Research", "quality", "score", "up", 0.12),
    ("financial_analysis", "Financial Analysis", "quality", "score", "up", 0.20),
    ("market_analysis", "Market Analysis", "quality", "score", "up", 0.18),
    ("verification", "Verification", "quality", "score", "up", 0.18),
    ("prompt_building", "Prompt Building", "quality", "score", "up", 0.10),
    ("summarization", "Summarization", "quality", "score", "up", 0.08),
    ("memory_curation", "Memory Curation", "quality", "score", "up", 0.08),
    ("ux_design", "UX Design", "quality", "score", "up", 0.12),
    ("vision", "Vision", "modality", "boolean", "up", 0.0),
    ("image_generation", "Image Generation", "modality", "boolean", "up", 0.0),
    ("image_editing", "Image Editing", "modality", "boolean", "up", 0.0),
    ("audio", "Audio", "modality", "boolean", "up", 0.0),
    ("pdf", "PDF", "modality", "boolean", "up", 0.0),
    ("long_context", "Long Context", "ops", "score", "up", 0.06),
    ("latency", "Latency", "ops", "score", "up", 0.05),
    ("reliability", "Reliability", "ops", "score", "up", 0.10),
    ("subscription_backed", "Subscription Backed", "ops", "boolean", "up", 0.0),
)

WORKLOAD_SEEDS: dict[str, dict[str, Any]] = {
    "general": {"label": "General", "requirements": {}, "constraints": {}, "risk": "normal", "verifier": "optional", "mode": "auto"},
    "planning": {"label": "Planning/Orchestration", "requirements": {"planning_orchestration": 1.0, "reasoning": 0.7, "instruction": 0.5}, "constraints": {}, "risk": "normal", "verifier": "optional", "mode": "auto"},
    "jenny_planning": {"label": "Jenny Planning", "requirements": {"planning_orchestration": 1.0, "tool_use": 0.7, "reasoning": 0.8}, "constraints": {}, "risk": "critical", "verifier": "required", "mode": "manual_locked"},
    "coding_impl": {"label": "Coding Implementation", "requirements": {"coding": 1.0, "swe_agentic": 0.9, "tool_use": 0.7}, "constraints": {"tool_use": True}, "risk": "normal", "verifier": "optional", "mode": "auto"},
    "code_review": {"label": "Code Review", "requirements": {"code_review": 1.0, "reasoning": 0.8, "strict_json": 0.4}, "constraints": {}, "risk": "elevated", "verifier": "optional", "mode": "auto"},
    "verifier": {"label": "Verifier", "requirements": {"verification": 1.0, "reasoning": 0.9, "strict_json": 0.8}, "constraints": {}, "risk": "critical", "verifier": "required", "mode": "manual_locked"},
    "finance_research": {"label": "Finance Research", "requirements": {"financial_analysis": 1.0, "data_research": 0.8, "reasoning": 0.9}, "constraints": {}, "risk": "critical", "verifier": "required", "mode": "manual_locked"},
    "trade_strategy": {"label": "Trade Strategy", "requirements": {"financial_analysis": 1.0, "market_analysis": 0.9, "reasoning": 1.0}, "constraints": {}, "risk": "critical", "verifier": "required", "mode": "manual_locked"},
    "market_scan": {"label": "Market Scan", "requirements": {"market_analysis": 1.0, "data_research": 0.8, "summarization": 0.4}, "constraints": {}, "risk": "critical", "verifier": "required", "mode": "manual_locked"},
    "data_analysis": {"label": "Data Analysis", "requirements": {"data_analysis": 1.0, "math": 0.6, "reasoning": 0.6}, "constraints": {}, "risk": "normal", "verifier": "optional", "mode": "auto"},
    "deep_research": {"label": "Deep Research", "requirements": {"data_research": 1.0, "reasoning": 0.8, "long_context": 0.6}, "constraints": {}, "risk": "elevated", "verifier": "optional", "mode": "auto"},
    "prompt_building": {"label": "Prompt Building", "requirements": {"prompt_building": 1.0, "instruction": 0.8}, "constraints": {}, "risk": "normal", "verifier": "optional", "mode": "auto"},
    "summarization": {"label": "Summarization", "requirements": {"summarization": 1.0, "instruction": 0.5, "latency": 0.4}, "constraints": {}, "risk": "low", "verifier": "optional", "mode": "auto"},
    "memory_curation": {"label": "Memory Curation", "requirements": {"memory_curation": 1.0, "summarization": 0.7, "instruction": 0.6}, "constraints": {}, "risk": "normal", "verifier": "optional", "mode": "auto"},
    "ui_design": {"label": "UI Design", "requirements": {"ux_design": 1.0, "vision": 0.5, "instruction": 0.5}, "constraints": {}, "risk": "normal", "verifier": "optional", "mode": "auto"},
    "vision_qa": {"label": "Vision QA", "requirements": {"vision": 1.0, "reasoning": 0.5}, "constraints": {"vision": True}, "risk": "normal", "verifier": "optional", "mode": "auto"},
    "image_generation": {"label": "Image Generation", "requirements": {"image_generation": 1.0, "ux_design": 0.4}, "constraints": {"image_generation": True}, "risk": "normal", "verifier": "optional", "mode": "manual_locked"},
    "voice_response": {"label": "Voice Response", "requirements": {"audio": 1.0, "latency": 0.7, "instruction": 0.6}, "constraints": {"audio": True}, "risk": "normal", "verifier": "optional", "mode": "auto"},
}


@dataclass(frozen=True)
class RoutingContext:
    """Request facts used for model routing."""

    request_id: str | None = None
    session_id: str | None = None
    project_id: str | None = None
    task_type: str | None = None
    phase: str | None = None
    workload_profile: str | None = None
    work_context: dict[str, Any] | None = None
    has_tools: bool = False
    requires_json: bool = False
    has_vision_input: bool = False
    requires_audio: bool = False
    max_context_tokens: int | None = None
    routing_mode_override: str | None = None
    canary_percent: float = 0.0
    adhoc: bool = False
    routing_requirements: dict[str, float] | None = None
    routing_constraints: dict[str, Any] | None = None
    routing_risk_tier: str | None = None
    routing_cost_preference: str | None = None
    routing_exclude_providers: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModelRoute:
    """Resolved model chain and route audit data."""

    mode: RoutingMode
    workload_profile: str
    primary_model_id: str
    fallback_models: list[str]
    escalation_model_id: str | None
    provider: str
    manual_route_id: int | None = None
    auto_candidate_model_id: str | None = None
    auto_candidate_fallbacks: list[str] = field(default_factory=list)
    decision_id: str | None = None
    canary_percent: float = 0.0
    score_breakdown: dict[str, Any] = field(default_factory=dict)

    @property
    def chain(self) -> list[str]:
        return _unique([self.primary_model_id, *self.fallback_models, *( [self.escalation_model_id] if self.escalation_model_id else [])])


class RoutingSelectionError(RuntimeError):
    """Raised when no model satisfies routing constraints."""


async def ensure_adaptive_routing_seed_data(db: AsyncSession) -> int:
    """Insert missing routing dimensions, workloads, profiles, manual routes, and availability."""
    inserted = 0
    existing_dimensions = set((await db.execute(select(CapabilityDimension.key))).scalars().all())
    for key, label, category, value_type, direction, weight in DIMENSION_SEEDS:
        if key in existing_dimensions:
            continue
        db.add(
            CapabilityDimension(
                key=key,
                label=label,
                category=category,
                value_type=value_type,
                direction=direction,
                default_weight=weight,
            )
        )
        inserted += 1

    existing_workloads = {
        workload.key: workload
        for workload in (await db.execute(select(WorkloadProfile))).scalars().all()
    }
    for key, data in WORKLOAD_SEEDS.items():
        workload = existing_workloads.get(key)
        if workload is not None:
            before = (
                workload.label,
                workload.requirement_deltas,
                workload.hard_constraints,
                workload.risk_tier,
                workload.verifier_policy,
                workload.default_routing_mode,
            )
            workload.label = data["label"]
            workload.requirement_deltas = data["requirements"]
            workload.hard_constraints = data["constraints"]
            workload.risk_tier = data["risk"]
            workload.verifier_policy = data["verifier"]
            workload.default_routing_mode = data["mode"]
            after = (
                workload.label,
                workload.requirement_deltas,
                workload.hard_constraints,
                workload.risk_tier,
                workload.verifier_policy,
                workload.default_routing_mode,
            )
            if before != after:
                inserted += 1
            continue
        db.add(
            WorkloadProfile(
                key=key,
                label=data["label"],
                requirement_deltas=data["requirements"],
                hard_constraints=data["constraints"],
                risk_tier=data["risk"],
                verifier_policy=data["verifier"],
                default_routing_mode=data["mode"],
            )
        )
        inserted += 1

    await db.flush()
    inserted += await _ensure_agent_profiles_and_manual_routes(db)
    inserted += await refresh_catalog_model_availability(db)
    if inserted:
        await db.commit()
    return inserted


async def _ensure_agent_profiles_and_manual_routes(db: AsyncSession) -> int:
    inserted = 0
    result = await db.execute(select(Agent).where(Agent.is_active == True).order_by(Agent.slug))  # noqa: E712
    agents = result.scalars().all()
    existing_profiles = set((await db.execute(select(AgentRoutingProfile.agent_slug))).scalars().all())
    existing_manual = set(
        (await db.execute(
            select(ManualModelRoute.agent_slug).where(
                ManualModelRoute.enabled == True,  # noqa: E712
                ManualModelRoute.workload_profile.is_(None),
            )
        )).scalars().all()
    )
    existing_overrides = {
        (agent_slug, workload_profile)
        for agent_slug, workload_profile in (
            await db.execute(
                select(
                    AgentWorkloadRoutingMode.agent_slug,
                    AgentWorkloadRoutingMode.workload_profile,
                )
            )
        ).all()
    }
    active_agent_slugs = {agent.slug for agent in agents}
    for agent in agents:
        critical = agent.slug in CRITICAL_AGENT_SLUGS
        expected_mode: RoutingMode = "manual_locked" if critical else SYSTEM_DEFAULT_MODE
        expected_risk = "critical" if critical else "normal"
        expected_exploration = "disabled" if critical else "auto"
        if agent.slug not in existing_profiles:
            db.add(
                AgentRoutingProfile(
                    agent_slug=agent.slug,
                    default_routing_mode=expected_mode,
                    risk_tier=expected_risk,
                    exploration_policy=expected_exploration,
                    cost_policy="subscription_first",
                    subscription_policy="prefer_subscription",
                    metadata_={"source": PROFILE_METADATA_SOURCE},
                )
            )
            inserted += 1
        else:
            profile = await db.get(AgentRoutingProfile, agent.slug)
            if profile is not None and _should_reconcile_profile(profile, critical):
                before = (
                    profile.default_routing_mode,
                    profile.risk_tier,
                    profile.exploration_policy,
                    profile.metadata_,
                )
                profile.default_routing_mode = expected_mode
                profile.risk_tier = expected_risk
                profile.exploration_policy = expected_exploration
                profile.cost_policy = profile.cost_policy or "subscription_first"
                profile.subscription_policy = profile.subscription_policy or "prefer_subscription"
                metadata = dict(profile.metadata_ or {})
                metadata["source"] = PROFILE_METADATA_SOURCE
                profile.metadata_ = metadata
                after = (
                    profile.default_routing_mode,
                    profile.risk_tier,
                    profile.exploration_policy,
                    profile.metadata_,
                )
                if before != after:
                    inserted += 1
        if agent.slug not in existing_manual:
            db.add(
                ManualModelRoute(
                    agent_slug=agent.slug,
                    primary_model_id=resolve_model(agent.primary_model_id),
                    fallback_models=[resolve_model(model) for model in agent.fallback_models or []],
                    escalation_model_id=resolve_model(agent.escalation_model_id) if agent.escalation_model_id else None,
                    reason="Seeded from legacy agent model chain",
                    owner="startup",
                    allow_health_fallback=False,
                    enabled=True,
                )
            )
            inserted += 1
    for agent_slug, workload_profile, canary_percent in LOW_RISK_CANARY_OVERRIDES:
        if agent_slug not in active_agent_slugs:
            continue
        if (agent_slug, workload_profile) in existing_overrides:
            continue
        db.add(
            AgentWorkloadRoutingMode(
                agent_slug=agent_slug,
                workload_profile=workload_profile,
                routing_mode="auto_canary",
                canary_percent=canary_percent,
                reason="Initial low-risk adaptive routing canary",
                owner="startup_seed",
                enabled=True,
            )
        )
        inserted += 1
    return inserted


def _should_reconcile_profile(profile: AgentRoutingProfile, critical: bool) -> bool:
    """Return true when startup may manage profile mode defaults."""
    metadata = profile.metadata_ or {}
    source = metadata.get("source")
    if source in {"manual_override", "user_override"}:
        return False
    if critical:
        return True
    return source in MANAGED_PROFILE_SOURCES or profile.default_routing_mode == "auto_shadow"


async def refresh_catalog_model_availability(db: AsyncSession) -> int:
    """Refresh availability rows for active catalog models using configured credentials."""
    credential_manager = get_credential_manager()
    models = (await db.execute(select(ModelCatalogEntry).where(ModelCatalogEntry.is_active == True))).scalars().all()  # noqa: E712
    existing_rows = {
        (row.model_id, row.provider): row
        for row in (await db.execute(select(ModelAvailability))).scalars().all()
    }
    changed = 0
    entitlement_by_provider, entitlement_changes = await _refresh_provider_entitlements(
        db,
        {model.provider for model in models},
    )
    changed += entitlement_changes
    active_entitled_providers = set(
        (
            await db.execute(
                select(ProviderEntitlement.provider).where(
                    ProviderEntitlement.enabled == True,  # noqa: E712
                    ProviderEntitlement.status == "active",
                )
            )
        ).scalars().all()
    )
    for model in models:
        available = _provider_available(model.provider, credential_manager) or model.provider in active_entitled_providers
        row = existing_rows.get((model.id, model.provider))
        snapshot = {
            "vision": bool(model.has_vision),
            "image_generation": bool(model.can_generate_images),
            "image_editing": bool(model.can_edit_images),
            "audio": bool(model.supports_audio),
            "pdf": bool(model.supports_pdf),
            "tool_use": bool(model.supports_tool_execution),
            "context_window": int(model.context_window),
            "source": "catalog",
        }
        if row is None:
            db.add(
                ModelAvailability(
                    model_id=model.id,
                    provider=model.provider,
                    entitlement_id=entitlement_by_provider.get(model.provider),
                    discovered_name=model.name,
                    routable=available,
                    enabled=True,
                    last_smoke_status="seed_trusted" if available else "provider_unavailable",
                    last_smoke_at=datetime.now(UTC) if available else None,
                    failure_reason=None if available else "Provider entitlement not configured",
                    capabilities_snapshot=snapshot,
                )
            )
            changed += 1
        else:
            before = (row.routable, row.entitlement_id, row.last_smoke_status, row.failure_reason, row.capabilities_snapshot)
            row.routable = available and row.enabled
            row.entitlement_id = entitlement_by_provider.get(model.provider)
            row.last_smoke_status = "seed_trusted" if available else "provider_unavailable"
            row.failure_reason = None if available else "Provider entitlement not configured"
            row.capabilities_snapshot = snapshot
            if before != (row.routable, row.entitlement_id, row.last_smoke_status, row.failure_reason, row.capabilities_snapshot):
                changed += 1
    return changed


async def resolve_model_route(
    db: AsyncSession,
    agent: AgentDTO,
    context: RoutingContext | None = None,
) -> tuple[AgentDTO, ModelRoute]:
    """Resolve an agent to an effective model chain."""
    context = context or RoutingContext()
    workload_key = await _infer_workload(db, agent, context)
    workload = await _get_workload(db, workload_key)
    profile = await _get_agent_profile(db, agent)
    override = await _get_workload_override(db, agent.slug, workload.key)
    mode = _mode_from_policy(workload, profile, context, override)
    canary_percent = _canary_percent_from_policy(context, override)
    manual = await _get_manual_route(db, agent.slug, workload_key)
    manual_chain = _manual_chain(agent, manual)
    auto_route = await _auto_route(db, agent, workload, profile, context, manual_chain)
    execute_auto = mode == "auto" or (mode == "auto_canary" and _canary_hit(agent.slug, workload_key, context, canary_percent))
    if mode in {"manual_locked", "auto_shadow"}:
        selected = manual_chain
    elif execute_auto:
        selected = auto_route
    else:
        selected = manual_chain

    provider = get_provider_for_model(selected.primary_model_id)
    decision = await _record_routing_decision(
        db,
        agent=agent,
        context=context,
        workload=workload,
        mode=mode,
        selected=selected,
        auto_route=auto_route,
        manual_route_id=manual.id if manual else None,
        provider=provider,
        canary_percent=canary_percent,
    )
    route = ModelRoute(
        mode=mode,
        workload_profile=workload.key,
        primary_model_id=selected.primary_model_id,
        fallback_models=selected.fallback_models,
        escalation_model_id=selected.escalation_model_id,
        provider=provider,
        manual_route_id=manual.id if manual else None,
        auto_candidate_model_id=auto_route.primary_model_id,
        auto_candidate_fallbacks=auto_route.fallback_models,
        decision_id=decision.id if decision else None,
        canary_percent=canary_percent,
        score_breakdown=selected.score_breakdown,
    )
    routed_agent = replace(
        agent,
        primary_model_id=route.primary_model_id,
        fallback_models=list(route.fallback_models),
        escalation_model_id=route.escalation_model_id,
    )
    return routed_agent, route


async def mark_routing_decision_completed(
    db: AsyncSession | None,
    decision_id: str | None,
    *,
    status: str = "completed",
    latency_ms: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    fallback_reason: str | None = None,
) -> None:
    """Persist completion facts onto a routing decision."""
    if not db or not decision_id:
        return
    decision = await db.get(RoutingDecision, decision_id)
    if decision is None:
        return
    decision.status = status
    decision.latency_ms = latency_ms
    decision.input_tokens = input_tokens
    decision.output_tokens = output_tokens
    if fallback_reason:
        decision.fallback_reason = fallback_reason
    decision.completed_at = datetime.now(UTC)
    await db.commit()


async def update_performance_from_verifier_outcome(
    db: AsyncSession,
    *,
    agent_slug: str,
    model_id: str,
    workload_profile: str,
    score: float,
    passed: bool,
) -> None:
    """Update rolling model/workload performance from verifier or human outcome."""
    row = await db.scalar(
        select(ModelWorkloadPerformance).where(
            ModelWorkloadPerformance.agent_slug == agent_slug,
            ModelWorkloadPerformance.workload_profile == workload_profile,
            ModelWorkloadPerformance.model_id == model_id,
        )
    )
    if row is None:
        row = ModelWorkloadPerformance(
            agent_slug=agent_slug,
            workload_profile=workload_profile,
            model_id=model_id,
            rolling_score=float(score),
            pass_rate=100.0 if passed else 0.0,
            verifier_score=float(score),
            sample_count=1,
            confidence=0.2,
        )
        db.add(row)
        return
    samples = max(0, row.sample_count)
    new_samples = samples + 1
    row.rolling_score = ((row.rolling_score * samples) + float(score)) / new_samples
    existing_pass_rate = row.pass_rate if row.pass_rate is not None else 0.0
    row.pass_rate = ((existing_pass_rate * samples) + (100.0 if passed else 0.0)) / new_samples
    existing_verifier = row.verifier_score if row.verifier_score is not None else row.rolling_score
    row.verifier_score = ((existing_verifier * samples) + float(score)) / new_samples
    row.sample_count = new_samples
    row.confidence = min(1.0, row.confidence + 0.05)


async def _refresh_provider_entitlements(db: AsyncSession, providers: set[str]) -> tuple[dict[str, int], int]:
    credential_manager = get_credential_manager()
    rows = {
        row.provider: row
        for row in (await db.execute(select(ProviderEntitlement).where(ProviderEntitlement.enabled == True))).scalars().all()  # noqa: E712
    }
    ids: dict[str, int] = {}
    changed = 0
    for provider in providers:
        available = _provider_available(provider, credential_manager)
        auth_mode = _provider_auth_mode(provider)
        metadata = _provider_entitlement_metadata(provider)
        row = rows.get(provider)
        if row is None:
            metadata["last_credential_probe"] = "active" if available else "missing"
            row = ProviderEntitlement(
                provider=provider,
                auth_mode=auth_mode,
                status="active" if available else "missing",
                discovery_source="credential_cache",
                metadata_=metadata,
                enabled=True,
                last_verified_at=datetime.now(UTC),
            )
            db.add(row)
            await db.flush()
            changed += 1
        else:
            before = (row.auth_mode, row.status, row.metadata_)
            existing_status = row.status
            probe_status = "active" if available else "missing"
            row.auth_mode = auth_mode
            row.status = "active" if available else existing_status
            row.metadata_ = {
                **metadata,
                **(row.metadata_ or {}),
                "last_credential_probe": probe_status,
            }
            row.last_verified_at = datetime.now(UTC)
            if before != (row.auth_mode, row.status, row.metadata_):
                changed += 1
        ids[provider] = row.id
    return ids, changed


def _provider_entitlement_metadata(provider: str) -> dict[str, Any]:
    default = {"subscription_first": provider in {"codex", "claude", "kimi-code", "minimax"}}
    return {**default, **PROVIDER_ROUTING_METADATA.get(provider, {})}


def _provider_auth_mode(provider: str) -> str:
    if provider in {"codex", "claude"}:
        return "oauth_subscription"
    if provider in {"kimi-code", "minimax"}:
        return "subscription"
    if provider == "local":
        return "local"
    return "api_key"


def _provider_available(provider: str, credential_manager: Any) -> bool:
    if provider == "codex":
        return bool(credential_manager.get("codex", "oauth_token"))
    if provider == "claude":
        return bool(credential_manager.get("claude", "oauth_token") or shutil.which("claude"))
    if provider == "gemini":
        return bool(credential_manager.get_api_keys("gemini"))
    if provider == "local":
        return bool(credential_manager.get("local", "api_key"))
    return bool(credential_manager.get_api_key(provider))


async def _infer_workload(db: AsyncSession, agent: AgentDTO, context: RoutingContext) -> str:
    if context.workload_profile and await _workload_exists(db, context.workload_profile):
        return context.workload_profile
    if context.work_context:
        maybe_workload = context.work_context.get("workload_profile") or context.work_context.get("workload")
        if isinstance(maybe_workload, str) and await _workload_exists(db, maybe_workload):
            return maybe_workload
    runtime_requirements = context.routing_requirements or {}
    if runtime_requirements:
        weighted = {key for key, value in runtime_requirements.items() if float(value or 0) > 0}
        if {"code_review", "verification"} & weighted:
            return "code_review" if "code_review" in weighted else "verifier"
        if {"coding", "swe_agentic", "tool_use"} & weighted:
            return "coding_impl"
        if {"financial_analysis", "market_analysis"} & weighted:
            return "finance_research"
        if "planning_orchestration" in weighted:
            return "planning"
        if "data_research" in weighted:
            return "deep_research"
        if "data_analysis" in weighted:
            return "data_analysis"
        if "ux_design" in weighted:
            return "ui_design"
    if context.adhoc:
        return "general"
    task_type = (context.task_type or "").lower()
    phase = (context.phase or "").lower()
    if agent.slug == "persona":
        return "jenny_planning"
    if agent.slug == "verifier":
        return "verifier"
    if agent.slug == "image-gen":
        return "image_generation"
    if agent.slug == "voice-responder" or context.requires_audio:
        return "voice_response"
    if agent.slug in FINANCE_AGENT_SLUGS:
        if "trade" in agent.slug or "trade" in task_type:
            return "trade_strategy"
        if "market" in agent.slug or "market" in task_type:
            return "market_scan"
        return "finance_research"
    if context.has_vision_input:
        return "vision_qa"
    if "review" in task_type or phase == "review" or agent.slug in {"reviewer", "critic"}:
        return "code_review"
    if agent.slug in {"planner", "supervisor", "task-sweep-orchestrator", "triager", "complexity-assessor"}:
        return "planning"
    if agent.slug in {"researcher", "analyst", "reasoner"}:
        return "deep_research"
    if "research" in task_type:
        return "deep_research"
    if "data" in task_type:
        return "data_analysis"
    if agent.slug in UTILITY_AGENT_SLUGS:
        return "memory_curation" if "memory" in agent.slug or "learning" in agent.slug else "summarization"
    if agent.slug in {"designer", "ui-mockup-designer", "ux-polisher", "site-checker"}:
        return "ui_design"
    if agent.slug in {"prompt-builder", "specifier"}:
        return "prompt_building"
    if agent.is_coding_agent or agent.slug in {"coder", "debugger", "refactor", "optimizer", "dependency-manager"}:
        return "coding_impl"
    return "general"


async def _workload_exists(db: AsyncSession, key: str) -> bool:
    return bool(await db.scalar(select(WorkloadProfile.key).where(WorkloadProfile.key == key)))


async def _get_workload(db: AsyncSession, key: str) -> WorkloadProfile:
    workload = await db.get(WorkloadProfile, key)
    if workload:
        return workload
    return WorkloadProfile(
        key="general",
        label="General",
        requirement_deltas={},
        hard_constraints={},
        risk_tier="normal",
        verifier_policy="optional",
        default_routing_mode=SYSTEM_DEFAULT_MODE,
    )


async def _get_agent_profile(db: AsyncSession, agent: AgentDTO) -> AgentRoutingProfile:
    profile = await db.get(AgentRoutingProfile, agent.slug)
    if profile:
        return profile
    critical = agent.slug in CRITICAL_AGENT_SLUGS
    return AgentRoutingProfile(
        agent_slug=agent.slug,
        default_routing_mode="manual_locked" if critical else SYSTEM_DEFAULT_MODE,
        risk_tier="critical" if critical else "normal",
        cost_policy="subscription_first",
        subscription_policy="prefer_subscription",
        exploration_policy="disabled" if critical else "auto",
        metadata_={"source": PROFILE_METADATA_SOURCE},
    )


async def _get_workload_override(
    db: AsyncSession,
    agent_slug: str,
    workload_key: str,
) -> AgentWorkloadRoutingMode | None:
    return await db.scalar(
        select(AgentWorkloadRoutingMode).where(
            AgentWorkloadRoutingMode.agent_slug == agent_slug,
            AgentWorkloadRoutingMode.workload_profile == workload_key,
            AgentWorkloadRoutingMode.enabled == True,  # noqa: E712
        )
    )


def _mode_from_policy(
    workload: WorkloadProfile,
    profile: AgentRoutingProfile,
    context: RoutingContext,
    override: AgentWorkloadRoutingMode | None,
) -> RoutingMode:
    if context.routing_mode_override in ROUTING_MODES:
        return context.routing_mode_override  # type: ignore[return-value]
    if context.adhoc:
        return "auto"
    if override and override.routing_mode in ROUTING_MODES:
        return override.routing_mode  # type: ignore[return-value]
    if profile.default_routing_mode == "manual_locked":
        return "manual_locked"
    if workload.default_routing_mode in ROUTING_MODES:
        return workload.default_routing_mode  # type: ignore[return-value]
    if profile.default_routing_mode in ROUTING_MODES:
        return profile.default_routing_mode  # type: ignore[return-value]
    return SYSTEM_DEFAULT_MODE


def _canary_percent_from_policy(
    context: RoutingContext,
    override: AgentWorkloadRoutingMode | None,
) -> float:
    if context.canary_percent > 0:
        return context.canary_percent
    if override:
        return float(override.canary_percent or 0.0)
    return 0.0


async def _get_manual_route(db: AsyncSession, agent_slug: str, workload_key: str) -> ManualModelRoute | None:
    now = datetime.now(UTC)
    exact = await db.scalar(
        select(ManualModelRoute)
        .where(
            ManualModelRoute.agent_slug == agent_slug,
            ManualModelRoute.workload_profile == workload_key,
            ManualModelRoute.enabled == True,  # noqa: E712
            or_(ManualModelRoute.expires_at.is_(None), ManualModelRoute.expires_at > now),
        )
        .order_by(desc(ManualModelRoute.created_at))
    )
    if exact:
        return exact
    return await db.scalar(
        select(ManualModelRoute)
        .where(
            ManualModelRoute.agent_slug == agent_slug,
            ManualModelRoute.workload_profile.is_(None),
            ManualModelRoute.enabled == True,  # noqa: E712
            or_(ManualModelRoute.expires_at.is_(None), ManualModelRoute.expires_at > now),
        )
        .order_by(desc(ManualModelRoute.created_at))
    )


@dataclass(frozen=True)
class _RouteCandidate:
    primary_model_id: str
    fallback_models: list[str]
    escalation_model_id: str | None
    score_breakdown: dict[str, Any]


def _manual_chain(agent: AgentDTO, manual: ManualModelRoute | None) -> _RouteCandidate:
    if manual:
        return _RouteCandidate(
            primary_model_id=resolve_model(manual.primary_model_id),
            fallback_models=[resolve_model(model) for model in manual.fallback_models or []],
            escalation_model_id=resolve_model(manual.escalation_model_id) if manual.escalation_model_id else None,
            score_breakdown={"manual_route_id": manual.id, "reason": manual.reason},
        )
    return _RouteCandidate(
        primary_model_id=resolve_model(agent.primary_model_id),
        fallback_models=[resolve_model(model) for model in agent.fallback_models or []],
        escalation_model_id=resolve_model(agent.escalation_model_id) if agent.escalation_model_id else None,
        score_breakdown={"legacy_agent_chain": True},
    )


async def _auto_route(
    db: AsyncSession,
    agent: AgentDTO,
    workload: WorkloadProfile,
    profile: AgentRoutingProfile,
    context: RoutingContext,
    manual_chain: _RouteCandidate,
) -> _RouteCandidate:
    rows = (await db.execute(select(ModelCatalogEntry).where(ModelCatalogEntry.is_active == True))).scalars().all()  # noqa: E712
    availability_rows = {
        row.model_id: row
        for row in (await db.execute(select(ModelAvailability).where(ModelAvailability.enabled == True))).scalars().all()  # noqa: E712
    }
    entitlement_rows = {
        row.provider: row
        for row in (await db.execute(select(ProviderEntitlement).where(ProviderEntitlement.enabled == True))).scalars().all()  # noqa: E712
    }
    capability_scores = await _load_model_capability_scores(db)
    perf_scores = await _load_performance_scores(db, agent.slug, workload.key)
    requirements = dict(workload.requirement_deltas or {})
    constraints = dict(workload.hard_constraints or {})
    for key, value in (context.routing_requirements or {}).items():
        requirements[key] = max(float(requirements.get(key, 0)), float(value))
    constraints.update(context.routing_constraints or {})
    if context.requires_json:
        requirements["strict_json"] = max(float(requirements.get("strict_json", 0)), 0.8)
    if context.has_tools:
        constraints["tool_use"] = True
        requirements["tool_use"] = max(float(requirements.get("tool_use", 0)), 0.7)
    if context.has_vision_input:
        constraints["vision"] = True
    risk_tier = context.routing_risk_tier or workload.risk_tier
    cost_policy = _effective_cost_policy(context.routing_cost_preference, profile.cost_policy)
    subscription_policy = profile.subscription_policy or "prefer_subscription"
    quality_floor = profile.quality_floor
    excluded_providers = {provider.lower() for provider in context.routing_exclude_providers}
    scored: list[tuple[float, ModelCatalogEntry, dict[str, Any]]] = []
    for row in rows:
        if row.provider.lower() in excluded_providers:
            continue
        availability = availability_rows.get(row.id)
        if not _availability_allows_routing(availability):
            continue
        if not _model_satisfies_constraints(row, constraints, context):
            continue
        entitlement = entitlement_rows.get(row.provider)
        subscription_backed = bool(
            entitlement
            and (
                entitlement.auth_mode in {"oauth_subscription", "subscription"}
                or (entitlement.metadata_ or {}).get("subscription_first")
            )
        )
        if subscription_policy in {"require_subscription", "subscription_only"} and not subscription_backed:
            continue
        score, breakdown = _score_model(
            row,
            requirements,
            capability_scores.get(row.id, {}),
            perf_scores.get(row.id),
            risk_tier,
            cost_policy=cost_policy,
            subscription_policy=subscription_policy,
            subscription_backed=subscription_backed,
            provider_policy=entitlement.metadata_ if entitlement else {},
            workload_requirements=requirements,
        )
        if quality_floor is not None and breakdown["fit_raw"] < float(quality_floor):
            continue
        scored.append((score, row, breakdown))
    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored:
        if context.adhoc:
            raise RoutingSelectionError(
                f"No routable model candidates for adhoc workload '{workload.key}' "
                f"after constraints/exclusions."
            )
        logger.warning("No auto-route candidates for agent=%s workload=%s; using manual chain", agent.slug, workload.key)
        return manual_chain
    primary = scored[0][1]
    fallback_models = _provider_diverse_fallbacks(scored[1:], primary.provider, limit=3)
    score_breakdown = {
        "score": scored[0][0],
        "requirements": requirements,
        "risk_tier": risk_tier,
        "cost_policy": cost_policy,
        "subscription_policy": subscription_policy,
        "quality_floor": quality_floor,
        "excluded_providers": sorted(excluded_providers),
        "primary": scored[0][2],
        "candidates": [
            {"model_id": row.id, "provider": row.provider, "score": round(score, 3)}
            for score, row, _breakdown in scored[:8]
        ],
    }
    return _RouteCandidate(
        primary_model_id=primary.id,
        fallback_models=fallback_models,
        escalation_model_id=fallback_models[0] if workload.risk_tier in {"elevated", "critical"} and fallback_models else None,
        score_breakdown=score_breakdown,
    )


async def _load_model_capability_scores(db: AsyncSession) -> dict[str, dict[str, float]]:
    now = datetime.now(UTC)
    result = await db.execute(
        select(ModelCapabilityScore).where(
            or_(ModelCapabilityScore.expires_at.is_(None), ModelCapabilityScore.expires_at > now)
        )
    )
    scores: dict[str, dict[str, float]] = {}
    for row in result.scalars().all():
        value = row.numeric_score
        if value is None and row.boolean_value is not None:
            value = 100.0 if row.boolean_value else 0.0
        if value is None:
            continue
        scores.setdefault(row.model_id, {})[row.dimension_key] = float(value)
    return scores


async def _load_performance_scores(db: AsyncSession, agent_slug: str, workload_key: str) -> dict[str, ModelWorkloadPerformance]:
    result = await db.execute(
        select(ModelWorkloadPerformance).where(
            ModelWorkloadPerformance.workload_profile == workload_key,
            or_(ModelWorkloadPerformance.agent_slug == agent_slug, ModelWorkloadPerformance.agent_slug.is_(None)),
        )
    )
    by_model: dict[str, ModelWorkloadPerformance] = {}
    for row in result.scalars().all():
        current = by_model.get(row.model_id)
        if current is None or (row.agent_slug == agent_slug and current.agent_slug is None):
            by_model[row.model_id] = row
    return by_model


def _model_satisfies_constraints(row: ModelCatalogEntry, constraints: dict[str, Any], context: RoutingContext) -> bool:
    if constraints.get("tool_use") and not row.supports_tool_execution:
        return False
    if constraints.get("vision") and not row.has_vision:
        return False
    if constraints.get("image_generation") and not row.can_generate_images:
        return False
    if constraints.get("image_editing") and not row.can_edit_images:
        return False
    if constraints.get("audio") and not row.supports_audio:
        return False
    if constraints.get("pdf") and not row.supports_pdf:
        return False
    return not (context.max_context_tokens and row.context_window < context.max_context_tokens)


def _availability_allows_routing(availability: ModelAvailability | None) -> bool:
    return bool(availability and availability.enabled and availability.routable)


def _effective_cost_policy(requested: str | None, profile_policy: str | None) -> str:
    if requested in {"quality", "balanced", "low_cost"}:
        return requested
    if profile_policy in {"quality", "balanced", "low_cost", "subscription_first"}:
        return profile_policy
    return "balanced"


def _score_model(
    row: ModelCatalogEntry,
    requirements: dict[str, float],
    capability_scores: dict[str, float],
    perf: ModelWorkloadPerformance | None,
    risk_tier: str,
    *,
    cost_policy: str = "balanced",
    subscription_policy: str = "prefer_subscription",
    subscription_backed: bool = False,
    provider_policy: dict[str, Any] | None = None,
    workload_requirements: dict[str, float] | None = None,
) -> tuple[float, dict[str, Any]]:
    base_scores = {
        "coding": row.score_coding,
        "swe_agentic": (row.score_coding * 0.7) + (row.score_tool_use * 0.3),
        "code_review": (row.score_reasoning * 0.55) + (row.score_instruction * 0.25) + (row.score_coding * 0.20),
        "planning_orchestration": row.score_planning,
        "reasoning": row.score_reasoning,
        "tool_use": row.score_tool_use,
        "instruction": row.score_instruction,
        "strict_json": (row.score_instruction * 0.65) + (row.score_tool_use * 0.35),
        "math": row.score_reasoning,
        "data_analysis": (row.score_reasoning * 0.65) + (row.score_tool_use * 0.35),
        "data_research": (row.score_planning * 0.45) + (row.score_reasoning * 0.35) + (row.score_instruction * 0.20),
        "financial_analysis": (row.score_reasoning * 0.60) + (row.score_planning * 0.25) + (row.score_instruction * 0.15),
        "market_analysis": (row.score_reasoning * 0.45) + (row.score_planning * 0.35) + (row.score_instruction * 0.20),
        "verification": (row.score_reasoning * 0.50) + (row.score_instruction * 0.30) + (row.score_tool_use * 0.20),
        "prompt_building": (row.score_instruction * 0.65) + (row.score_planning * 0.35),
        "summarization": (row.score_instruction * 0.70) + (row.score_reasoning * 0.30),
        "memory_curation": (row.score_instruction * 0.45) + (row.score_reasoning * 0.35) + (row.score_planning * 0.20),
        "ux_design": row.score_design,
        "vision": 100.0 if row.has_vision else 0.0,
        "image_generation": 100.0 if row.can_generate_images else 0.0,
        "image_editing": 100.0 if row.can_edit_images else 0.0,
        "audio": 100.0 if row.supports_audio else 0.0,
        "pdf": 100.0 if row.supports_pdf else 0.0,
        "long_context": min(100.0, row.context_window / 2000.0),
        "latency": {"fast": 95.0, "medium": 70.0, "slow": 45.0}.get(row.speed_tier, 60.0),
        "reliability": 75.0,
    }
    base_scores.update(capability_scores)
    if not requirements:
        requirements = {"reasoning": 0.4, "instruction": 0.4, "tool_use": 0.2}
    total_weight = sum(max(0.0, float(w)) for w in requirements.values()) or 1.0
    fit = sum(base_scores.get(dim, 0.0) * max(0.0, float(weight)) for dim, weight in requirements.items()) / total_weight
    perf_score = perf.rolling_score if perf and perf.sample_count else None
    reliability_penalty = 0.0
    if perf:
        reliability_penalty += (perf.timeout_rate or 0.0) * 0.25
        reliability_penalty += (perf.fallback_rate or 0.0) * 0.10
    adjustment_multiplier = 0.5 if risk_tier == "elevated" else 1.0
    routing_adjustment = 0.0
    if risk_tier == "critical":
        observed_weight = 0.30 if perf_score is not None else 0.0
        final = (fit * (1.0 - observed_weight)) + ((perf_score or 0.0) * observed_weight) - reliability_penalty
    elif risk_tier == "elevated":
        observed_weight = 0.20 if perf_score is not None else 0.0
        routing_adjustment = _routing_policy_adjustment(
            cost_policy,
            subscription_policy,
            subscription_backed,
            provider_policy,
            workload_requirements or requirements,
            penalty_multiplier=adjustment_multiplier,
        )
        final = (fit * (1.0 - observed_weight)) + ((perf_score or 0.0) * observed_weight) - reliability_penalty + routing_adjustment
    else:
        observed_weight = 0.15 if perf_score is not None else 0.0
        cost_multiplier = {
            "quality": 0.25,
            "balanced": 1.0,
            "low_cost": 2.0,
            "subscription_first": 0.75,
        }.get(cost_policy, 1.0)
        raw_cost = max(0.0, row.cost_input_per_m + row.cost_output_per_m)
        cost_penalty = min(16.0, (raw_cost / 10.0) * cost_multiplier)
        if subscription_backed:
            cost_penalty *= 0.2
        routing_adjustment = _routing_policy_adjustment(
            cost_policy,
            subscription_policy,
            subscription_backed,
            provider_policy,
            workload_requirements or requirements,
            penalty_multiplier=adjustment_multiplier,
        )
        final = (fit * (1.0 - observed_weight)) + ((perf_score or 0.0) * observed_weight) - cost_penalty - reliability_penalty + routing_adjustment
    return final, {
        "fit_raw": fit,
        "fit": round(fit, 3),
        "observed": perf_score,
        "cost_policy": cost_policy,
        "subscription_policy": subscription_policy,
        "subscription_backed": subscription_backed,
        "reliability_penalty": round(reliability_penalty, 3),
        "routing_adjustment": round(routing_adjustment, 3),
        "scores": {dim: round(base_scores.get(dim, 0.0), 3) for dim in requirements},
    }


def _routing_policy_adjustment(
    cost_policy: str,
    subscription_policy: str,
    subscription_backed: bool,
    provider_policy: dict[str, Any] | None,
    requirements: dict[str, float],
    *,
    penalty_multiplier: float,
) -> float:
    policy = provider_policy or {}
    weighted = {key for key, value in requirements.items() if float(value or 0) > 0}
    adjustment = 0.0
    if subscription_policy == "prefer_subscription" and subscription_backed:
        adjustment += 1.0
    if cost_policy == "quality":
        penalty_multiplier *= 0.25
    if cost_policy == "low_cost" and not subscription_backed:
        adjustment -= 2.0
    adjustment += float(policy.get("routine_auto_bonus") or 0.0)
    if {"coding", "swe_agentic"} & weighted:
        adjustment += float(policy.get("coding_auto_bonus") or 0.0)
    elif "code_review" in weighted:
        adjustment += float(policy.get("code_review_auto_bonus") or 0.0)
    else:
        adjustment -= float(policy.get("noncoding_auto_penalty") or 0.0) * penalty_multiplier
    if {"summarization", "memory_curation", "latency"} & weighted:
        adjustment += float(policy.get("utility_auto_bonus") or 0.0)
    if "vision" in weighted:
        adjustment += float(policy.get("vision_auto_bonus") or 0.0)
    if "planning_orchestration" in weighted:
        adjustment += float(policy.get("planning_auto_bonus") or 0.0)
    if {"reasoning", "data_research", "data_analysis"} & weighted:
        adjustment += float(policy.get("reasoning_auto_bonus") or 0.0)
    if "prompt_building" in weighted:
        adjustment += float(policy.get("prompt_auto_bonus") or 0.0)
    adjustment -= float(policy.get("routine_auto_penalty") or 0.0) * penalty_multiplier
    return adjustment


def _provider_diverse_fallbacks(scored: list[tuple[float, ModelCatalogEntry, dict[str, Any]]], primary_provider: str, *, limit: int) -> list[str]:
    seen_providers = {primary_provider}
    selected: list[str] = []
    for _score, row, _breakdown in scored:
        if row.provider in seen_providers:
            continue
        selected.append(row.id)
        seen_providers.add(row.provider)
        if len(selected) >= limit:
            return selected
    for _score, row, _breakdown in scored:
        if row.id in selected:
            continue
        selected.append(row.id)
        if len(selected) >= limit:
            break
    return selected


def _canary_hit(agent_slug: str, workload_key: str, context: RoutingContext, canary_percent: float) -> bool:
    percent = max(0.0, min(100.0, canary_percent))
    if percent <= 0:
        return False
    seed = f"{agent_slug}:{workload_key}:{context.request_id or context.session_id or ''}"
    bucket = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16) % 100
    return bucket < percent


async def _record_routing_decision(
    db: AsyncSession,
    *,
    agent: AgentDTO,
    context: RoutingContext,
    workload: WorkloadProfile,
    mode: RoutingMode,
    selected: _RouteCandidate,
    auto_route: _RouteCandidate,
    manual_route_id: int | None,
    provider: str,
    canary_percent: float,
) -> RoutingDecision | None:
    try:
        decision = RoutingDecision(
            request_id=context.request_id,
            session_id=context.session_id,
            agent_slug=agent.slug,
            workload_profile=workload.key,
            routing_mode=mode,
            input_features={
                "task_type": context.task_type,
                "phase": context.phase,
                "has_tools": context.has_tools,
                "requires_json": context.requires_json,
                "has_vision_input": context.has_vision_input,
                "canary_percent": canary_percent,
                "adhoc": context.adhoc,
                "routing_requirements": context.routing_requirements or {},
                "routing_constraints": context.routing_constraints or {},
                "routing_risk_tier": context.routing_risk_tier,
                "routing_cost_preference": context.routing_cost_preference,
                "routing_exclude_providers": list(context.routing_exclude_providers),
                "work_context_mode": (context.work_context or {}).get("mode"),
            },
            candidates=auto_route.score_breakdown.get("candidates", []),
            chosen_model_id=selected.primary_model_id,
            chosen_provider=provider,
            fallback_chain=list(selected.fallback_models),
            score_breakdown={
                "selected": selected.score_breakdown,
                "auto_candidate": {
                    "primary_model_id": auto_route.primary_model_id,
                    "fallback_models": auto_route.fallback_models,
                    "score_breakdown": auto_route.score_breakdown,
                },
                "canary_percent": canary_percent,
            },
            constraints_hit=workload.hard_constraints or {},
            manual_route_id=manual_route_id,
            status="selected",
        )
        db.add(decision)
        await db.flush()
        return decision
    except Exception:
        logger.debug("Failed to record routing decision", exc_info=True)
        return None


def _unique(values: list[str | None]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
