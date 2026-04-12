from __future__ import annotations

from datetime import UTC, datetime

from app.services.memory.context_builder import ProgressiveContext
from app.services.memory.context_builder_settings import (
    normalize_memory_config,
    resolve_continuity_settings,
    resolve_effective_memory_config,
    resolve_memory_consumer_profile,
)
from app.services.memory.context_injector_formatter import format_progressive_context
from app.services.memory.memory_models import MemoryScope, MemorySearchResult, MemorySource
from app.services.memory.settings import MemorySettingsDTO


def test_normalize_memory_config_materializes_core_fields_and_preserves_extensions() -> None:
    normalized = normalize_memory_config(
        {
            "include_mandates": False,
            "cross_project_enabled": True,
            "audience_tags": [" finance-relevant ", "finance-relevant", ""],
            "exclude_tags": ["draft"],
        }
    )

    assert normalized == {
        "cross_project_enabled": True,
        "injection_enabled": True,
        "project_index_enabled": True,
        "tool_capabilities_enabled": True,
        "include_mandates": False,
        "include_guardrails": True,
        "include_references": True,
        "reference_index_enabled": True,
        "continuity_enabled": True,
        "continuity_max_sessions": 5,
        "audience_tags": ["finance-relevant"],
        "exclude_tags": ["draft"],
        "exclude_memory_uuids": [],
    }


def test_resolve_memory_consumer_profile_uses_surface_specific_overrides() -> None:
    memory_config = {
        "consumer_profile": "agent_general",
        "runtime_consumer_profile": "agent_coding",
        "preview_consumer_profile": "agent_operator",
    }

    assert resolve_memory_consumer_profile(memory_config, surface="runtime") == "agent_coding"
    assert resolve_memory_consumer_profile(memory_config, surface="preview") == "agent_operator"


def test_resolve_memory_consumer_profile_preview_falls_back_to_runtime_profile() -> None:
    memory_config = {"runtime_consumer_profile": "agent_promptops"}

    assert resolve_memory_consumer_profile(memory_config, surface="runtime") == "agent_promptops"
    assert resolve_memory_consumer_profile(memory_config, surface="preview") == "agent_promptops"


def test_resolve_memory_consumer_profile_defaults_preview_to_agent_preview() -> None:
    assert resolve_memory_consumer_profile(None, surface="runtime") is None
    assert resolve_memory_consumer_profile(None, surface="preview") == "agent_preview"


def test_normalize_memory_config_canonicalizes_known_consumer_profiles() -> None:
    normalized = normalize_memory_config(
        {
            "consumer_profile": " agent_general ",
            "runtime_consumer_profile": "agent_coding",
            "preview_consumer_profile": "not-a-real-profile",
        }
    )

    assert normalized is not None
    assert normalized["consumer_profile"] == "agent_general"
    assert normalized["runtime_consumer_profile"] == "agent_coding"
    assert "preview_consumer_profile" not in normalized


def test_normalize_memory_config_folds_legacy_enabled_into_injection_enabled() -> None:
    normalized = normalize_memory_config({"enabled": False, "injection_enabled": True})

    assert normalized is not None
    assert normalized["injection_enabled"] is False
    assert normalized["project_index_enabled"] is True
    assert normalized["tool_capabilities_enabled"] is True
    assert normalized["include_mandates"] is False
    assert normalized["include_guardrails"] is False
    assert normalized["include_references"] is False
    assert normalized["continuity_enabled"] is False
    assert "enabled" not in normalized


def test_resolve_continuity_settings_prefers_custom_values_when_present() -> None:
    settings = MemorySettingsDTO(
        enabled=True,
        budget_enabled=True,
        total_budget=3500,
        continuity_enabled=True,
        continuity_max_sessions=5,
    )

    resolved = resolve_continuity_settings(
        settings,
        {
            "continuity_enabled": False,
            "continuity_max_sessions": 9,
            "cross_project_enabled": False,
            "live_sessions_enabled": True,
        },
    )

    assert resolved == (False, 9, False, True)


def test_resolve_effective_memory_config_inherits_global_defaults_when_custom_disabled() -> None:
    settings = MemorySettingsDTO(
        enabled=False,
        budget_enabled=True,
        total_budget=3500,
        continuity_enabled=False,
        continuity_max_sessions=7,
    )

    resolved = resolve_effective_memory_config(settings, None)

    assert resolved == {
        "injection_enabled": False,
        "project_index_enabled": True,
        "tool_capabilities_enabled": True,
        "include_mandates": False,
        "include_guardrails": False,
        "include_references": False,
        "reference_index_enabled": False,
        "continuity_enabled": False,
        "continuity_max_sessions": 7,
        "audience_tags": [],
        "exclude_tags": [],
        "exclude_memory_uuids": [],
    }


def test_normalize_memory_config_clears_subordinate_flags_when_injection_disabled() -> None:
    normalized = normalize_memory_config(
        {
            "injection_enabled": False,
            "include_mandates": True,
            "include_guardrails": True,
            "include_references": True,
            "continuity_enabled": True,
        }
    )

    assert normalized == {
        "injection_enabled": False,
        "project_index_enabled": True,
        "tool_capabilities_enabled": True,
        "include_mandates": False,
        "include_guardrails": False,
        "include_references": False,
        "reference_index_enabled": False,
        "continuity_enabled": False,
        "continuity_max_sessions": 5,
        "audience_tags": [],
        "exclude_tags": [],
        "exclude_memory_uuids": [],
    }


def test_normalize_memory_config_preserves_project_index_when_memory_injection_disabled() -> None:
    normalized = normalize_memory_config(
        {
            "injection_enabled": False,
            "project_index_enabled": False,
            "tool_capabilities_enabled": False,
            "include_references": True,
        }
    )

    assert normalized is not None
    assert normalized["injection_enabled"] is False
    assert normalized["project_index_enabled"] is False
    assert normalized["tool_capabilities_enabled"] is False
    assert normalized["include_references"] is False


def test_format_progressive_context_omits_mandate_line_for_reference_only_context() -> None:
    reference = MemorySearchResult(
        uuid="12345678-1234-1234-1234-123456789abc",
        content="**Prompt Examples**: Use examples only when they anchor output shape.",
        summary="Prompt examples guidance",
        rendered_content="**Prompt Examples**: Use examples only when they anchor output shape.",
        source=MemorySource.SYSTEM,
        relevance_score=0.9,
        created_at=datetime.now(UTC),
        scope=MemoryScope.GLOBAL,
    )

    rendered = format_progressive_context(
        ProgressiveContext(reference=[reference]),
        include_citations=True,
        consumer_profile="agent_preview",
    )

    assert "Mandates/Guardrails below are authoritative" not in rendered
    assert "## Selected References" in rendered
    assert "Summarize your work:" not in rendered


def test_format_progressive_context_includes_mandate_line_when_present() -> None:
    mandate = MemorySearchResult(
        uuid="87654321-1234-1234-1234-123456789abc",
        content="**Quality Checks**: Use dt for all quality checks.",
        summary="Quality tool usage",
        rendered_content="**Quality Checks**: Use dt for all quality checks.",
        source=MemorySource.SYSTEM,
        relevance_score=1.0,
        created_at=datetime.now(UTC),
        scope=MemoryScope.GLOBAL,
    )

    rendered = format_progressive_context(
        ProgressiveContext(mandates=[mandate]),
        include_citations=True,
        consumer_profile="agent_preview",
    )

    assert "Mandates/Guardrails below are authoritative" in rendered
    assert "Applied: [M:uuid8] or [G:uuid8]" in rendered
    assert "Summarize your work:" not in rendered
