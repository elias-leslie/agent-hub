"""Helpers for memory context-kind defaults and applicability matching."""

from __future__ import annotations

import re
from typing import Any

from .memory_models import MemoryApplicability, MemoryContextKind

_APPLICABILITY_KEYS = (
    "consumer_surfaces",
    "exclude_consumer_surfaces",
    "consumer_profiles",
    "exclude_consumer_profiles",
    "agent_slugs",
    "exclude_agent_slugs",
    "audience_tags",
    "exclude_audience_tags",
)
_TRIGGER_TASK_TYPE_ALIASES = {
    "testing": "test",
    "tests": "test",
    "deployment": "devops",
    "migrations": "database",
    "migration": "database",
}
_CONSUMER_SURFACE_ALIASES = {
    "claude": "claude_code",
    "claude_cli": "claude_code",
    "claude_code_cli": "claude_code",
    "claude_gpt": "claude_code",
    "claude_tui": "claude_code",
    "codex_cli": "codex",
    "codex_tui": "codex",
    "gemini_cli": "gemini",
    "gemini_tui": "gemini",
    "pi_cli": "pi",
    "pi_mono": "pi",
    "pi_tui": "pi",
    "completion": "agent_runtime",
    "internal": "agent_runtime",
    "runtime": "agent_runtime",
}


def normalize_context_identifier(value: str | None) -> str | None:
    """Normalize case, CamelCase, spaces, and hyphens to stable snake case."""
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    cleaned = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", cleaned)
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", cleaned)
    return cleaned.strip("_").lower() or None


def normalize_consumer_surface(value: str | None) -> str | None:
    """Return the canonical surface name shared by all TUI adapters."""
    normalized = normalize_context_identifier(value)
    if normalized is None:
        return None
    return _CONSUMER_SURFACE_ALIASES.get(normalized, normalized)


def normalize_agent_slug(value: str | None) -> str | None:
    """Normalize agent slugs while preserving their canonical hyphen style."""
    normalized = normalize_context_identifier(value)
    return normalized.replace("_", "-") if normalized else None


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        cleaned = item.strip()
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    return normalized


def default_context_kind(memory_type: str | None, tier: int | str | None) -> MemoryContextKind:
    """Derive the semantic context channel from legacy type/tier data."""
    memory_type_value = (memory_type or "").strip().lower()
    if memory_type_value == "continuity":
        return MemoryContextKind.CONTINUITY
    if memory_type_value in {"feedback", "journal"}:
        return MemoryContextKind.SIGNAL

    if isinstance(tier, str):
        tier_name = tier.strip().lower()
    elif isinstance(tier, int):
        tier_name = {1: "mandate", 2: "guardrail", 3: "reference", 4: "archive"}.get(tier, "")
    else:
        tier_name = ""
    if tier_name in {"mandate", "guardrail"}:
        return MemoryContextKind.POLICY
    return MemoryContextKind.REFERENCE


def normalize_context_kind(
    value: Any,
    *,
    memory_type: str | None = None,
    tier: int | str | None = None,
) -> MemoryContextKind:
    """Return a valid context kind with sane defaults."""
    if isinstance(value, MemoryContextKind):
        return value
    if isinstance(value, str):
        try:
            return MemoryContextKind(value.strip().lower())
        except ValueError:
            pass
    return default_context_kind(memory_type, tier)


def normalize_applicability(value: Any) -> MemoryApplicability:
    """Normalize arbitrary JSON-like applicability payloads."""
    if isinstance(value, MemoryApplicability):
        value = value.model_dump()
    if isinstance(value, dict):
        normalized: dict[str, list[str]] = {}
        for key in _APPLICABILITY_KEYS:
            items = _normalize_string_list(value.get(key))
            if key in {"consumer_surfaces", "exclude_consumer_surfaces"}:
                normalized[key] = list(
                    dict.fromkeys(
                        surface
                        for item in items
                        if (surface := normalize_consumer_surface(item))
                    )
                )
            elif key in {"consumer_profiles", "exclude_consumer_profiles"}:
                normalized[key] = list(
                    dict.fromkeys(
                        profile
                        for item in items
                        if (profile := normalize_context_identifier(item))
                    )
                )
            elif key in {"agent_slugs", "exclude_agent_slugs"}:
                normalized[key] = list(
                    dict.fromkeys(
                        slug
                        for item in items
                        if (slug := normalize_agent_slug(item))
                    )
                )
            else:
                normalized[key] = list(
                    dict.fromkeys(item.strip().lower() for item in items if item.strip())
                )
        return MemoryApplicability(**normalized)
    return MemoryApplicability()


def normalize_trigger_task_types(value: Any) -> list[str]:
    """Normalize trigger_task_types while preserving unknown values for audit visibility."""
    normalized: list[str] = []
    for item in _normalize_string_list(value):
        identifier = normalize_context_identifier(item)
        if identifier is None:
            continue
        identifier = _TRIGGER_TASK_TYPE_ALIASES.get(identifier, identifier)
        if identifier not in normalized:
            normalized.append(identifier)
    return normalized


def normalize_trigger_phases(value: Any) -> list[str]:
    """Normalize trigger_phases into a compact, deduplicated list."""
    return list(
        dict.fromkeys(
            identifier
            for item in _normalize_string_list(value)
            if (identifier := normalize_context_identifier(item))
        )
    )


def applicability_has_targets(value: MemoryApplicability | dict[str, Any] | None) -> bool:
    """Return True when applicability narrows the eligible audience."""
    resolved = normalize_applicability(value)
    return any(
        getattr(resolved, field_name)
        for field_name in (
            "consumer_surfaces",
            "consumer_profiles",
            "agent_slugs",
            "audience_tags",
        )
    )


def applicability_has_exclusions(value: MemoryApplicability | dict[str, Any] | None) -> bool:
    """Return True when applicability explicitly excludes some audience."""
    resolved = normalize_applicability(value)
    return any(
        getattr(resolved, field_name)
        for field_name in (
            "exclude_consumer_surfaces",
            "exclude_consumer_profiles",
            "exclude_agent_slugs",
            "exclude_audience_tags",
        )
    )


def applicability_matches(
    applicability: MemoryApplicability | dict[str, Any] | None,
    *,
    consumer_surface: str | None = None,
    consumer_profile: str | None = None,
    consumer_agent_slug: str | None = None,
    consumer_tags: list[str] | None = None,
) -> bool:
    """Return True when a memory applies to the current consumer."""
    resolved = normalize_applicability(applicability)
    consumer_surface = normalize_consumer_surface(consumer_surface)
    consumer_profile = normalize_context_identifier(consumer_profile)
    consumer_agent_slug = normalize_agent_slug(consumer_agent_slug)
    tag_set = {tag.strip().lower() for tag in consumer_tags or [] if tag.strip()}

    if resolved.consumer_surfaces and (
        not consumer_surface or consumer_surface not in resolved.consumer_surfaces
    ):
        return False
    if consumer_surface and consumer_surface in resolved.exclude_consumer_surfaces:
        return False

    if resolved.consumer_profiles and (
        not consumer_profile or consumer_profile not in resolved.consumer_profiles
    ):
        return False
    if consumer_profile and consumer_profile in resolved.exclude_consumer_profiles:
        return False

    if resolved.agent_slugs and (
        not consumer_agent_slug or consumer_agent_slug not in resolved.agent_slugs
    ):
        return False
    if consumer_agent_slug and consumer_agent_slug in resolved.exclude_agent_slugs:
        return False

    if resolved.audience_tags and not tag_set.intersection(resolved.audience_tags):
        return False
    return not tag_set.intersection(resolved.exclude_audience_tags)
