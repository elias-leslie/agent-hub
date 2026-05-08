"""Tests for adaptive model routing policy helpers."""

from __future__ import annotations

from app.models import AgentRoutingProfile, ModelAvailability, ModelCatalogEntry, WorkloadProfile
from app.services.adaptive_model_router import (
    RoutingContext,
    _availability_allows_routing,
    _effective_cost_policy,
    _mode_from_policy,
    _score_model,
    _should_reconcile_profile,
)


def _model(
    model_id: str,
    provider: str,
    *,
    coding: int,
    reasoning: int,
    planning: int,
    tool_use: int,
    instruction: int,
) -> ModelCatalogEntry:
    return ModelCatalogEntry(
        id=model_id,
        alias=model_id,
        name=model_id,
        hint="",
        provider=provider,
        score_coding=coding,
        score_reasoning=reasoning,
        score_planning=planning,
        score_tool_use=tool_use,
        score_instruction=instruction,
        score_design=50,
        cost_input_per_m=0,
        cost_output_per_m=0,
        pricing_unit="per_million_tokens",
        service_tiers={},
        context_window=200000,
        speed_tier="fast",
        can_generate_images=False,
        has_vision=False,
        can_edit_images=False,
        has_thinking=True,
        supports_pdf=False,
        supports_audio=False,
        supports_tool_execution=True,
        supports_verbosity=False,
        supports_xhigh=True,
        supports_session_cache=False,
        max_output_tokens=32000,
        is_active=True,
        sort_order=0,
        source="test",
    )


def test_subscription_first_conserves_codex_for_routine_coding() -> None:
    requirements = {"coding": 1.0, "swe_agentic": 0.9, "tool_use": 0.7}
    codex_score, codex_breakdown = _score_model(
        _model(
            "codex/gpt-5.5",
            "codex",
            coding=98,
            reasoning=99,
            planning=90,
            tool_use=91,
            instruction=94,
        ),
        requirements,
        {},
        None,
        "normal",
        cost_policy="subscription_first",
        subscription_policy="prefer_subscription",
        subscription_backed=True,
        provider_policy={"routine_auto_penalty": 8.0},
    )
    kimi_score, kimi_breakdown = _score_model(
        _model(
            "kimi-code/kimi-for-coding",
            "kimi-code",
            coding=90,
            reasoning=93,
            planning=88,
            tool_use=90,
            instruction=88,
        ),
        requirements,
        {},
        None,
        "normal",
        cost_policy="subscription_first",
        subscription_policy="prefer_subscription",
        subscription_backed=True,
        provider_policy={"routine_auto_bonus": 3.0},
    )

    assert kimi_score > codex_score
    assert codex_breakdown["routing_adjustment"] < 0
    assert kimi_breakdown["routing_adjustment"] > 0


def test_quality_cost_policy_weakens_routine_provider_penalty() -> None:
    requirements = {"reasoning": 1.0}
    subscription_first_score, _ = _score_model(
        _model(
            "codex/gpt-5.5",
            "codex",
            coding=98,
            reasoning=99,
            planning=90,
            tool_use=91,
            instruction=94,
        ),
        requirements,
        {},
        None,
        "normal",
        cost_policy="subscription_first",
        subscription_policy="prefer_subscription",
        subscription_backed=True,
        provider_policy={"routine_auto_penalty": 8.0},
    )
    quality_score, quality_breakdown = _score_model(
        _model(
            "codex/gpt-5.5",
            "codex",
            coding=98,
            reasoning=99,
            planning=90,
            tool_use=91,
            instruction=94,
        ),
        requirements,
        {},
        None,
        "normal",
        cost_policy="quality",
        subscription_policy="prefer_subscription",
        subscription_backed=True,
        provider_policy={"routine_auto_penalty": 8.0},
    )

    assert quality_score > subscription_first_score
    assert quality_breakdown["routing_adjustment"] == -1.0


def test_mode_policy_uses_auto_for_ordinary_profiles_and_lock_for_protected() -> None:
    workload = WorkloadProfile(
        key="coding_impl",
        label="Coding Implementation",
        requirement_deltas={},
        hard_constraints={},
        risk_tier="normal",
        verifier_policy="optional",
        default_routing_mode="auto",
    )
    profile = AgentRoutingProfile(
        agent_slug="coder",
        default_routing_mode="auto",
        risk_tier="normal",
    )
    locked = AgentRoutingProfile(
        agent_slug="persona",
        default_routing_mode="manual_locked",
        risk_tier="critical",
    )

    assert _mode_from_policy(workload, profile, RoutingContext(), None) == "auto"
    assert _mode_from_policy(workload, locked, RoutingContext(), None) == "manual_locked"


def test_startup_reconciles_only_managed_profiles() -> None:
    managed = AgentRoutingProfile(
        agent_slug="coder",
        default_routing_mode="auto_shadow",
        metadata_={"source": "migration"},
    )
    manual = AgentRoutingProfile(
        agent_slug="coder",
        default_routing_mode="manual_locked",
        metadata_={"source": "manual_override"},
    )
    already_enabled = AgentRoutingProfile(
        agent_slug="coder",
        default_routing_mode="auto",
        metadata_={"source": "auto-routing-enable-v1"},
    )
    critical_user_override = AgentRoutingProfile(
        agent_slug="verifier",
        default_routing_mode="auto_canary",
        metadata_={"source": "user_override"},
    )

    assert _should_reconcile_profile(managed, critical=False) is True
    assert _should_reconcile_profile(manual, critical=False) is False
    assert _should_reconcile_profile(already_enabled, critical=False) is False
    assert _should_reconcile_profile(critical_user_override, critical=True) is False
    assert _effective_cost_policy(None, "subscription_first") == "subscription_first"


def test_missing_or_disabled_availability_is_not_routable() -> None:
    assert _availability_allows_routing(None) is False
    assert (
        _availability_allows_routing(
            ModelAvailability(model_id="missing", provider="test", enabled=True, routable=False)
        )
        is False
    )
    assert (
        _availability_allows_routing(
            ModelAvailability(model_id="disabled", provider="test", enabled=False, routable=True)
        )
        is False
    )
    assert (
        _availability_allows_routing(ModelAvailability(model_id="ok", provider="test", enabled=True, routable=True))
        is True
    )
