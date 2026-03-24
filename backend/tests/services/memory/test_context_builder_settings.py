from __future__ import annotations

from datetime import UTC, datetime

from app.services.memory.context_builder import ProgressiveContext
from app.services.memory.context_builder_settings import (
    normalize_memory_config,
    resolve_continuity_settings,
    resolve_effective_memory_config,
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
        "include_mandates": False,
        "include_guardrails": True,
        "include_references": True,
        "continuity_enabled": True,
        "continuity_max_sessions": 5,
        "audience_tags": ["finance-relevant"],
        "exclude_tags": ["draft"],
    }


def test_normalize_memory_config_folds_legacy_enabled_into_injection_enabled() -> None:
    normalized = normalize_memory_config({"enabled": False, "injection_enabled": True})

    assert normalized is not None
    assert normalized["injection_enabled"] is False
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
        "include_mandates": True,
        "include_guardrails": True,
        "include_references": True,
        "continuity_enabled": False,
        "continuity_max_sessions": 7,
        "audience_tags": [],
        "exclude_tags": [],
    }


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
