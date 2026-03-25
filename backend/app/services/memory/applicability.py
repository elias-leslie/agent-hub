"""Helpers for memory context-kind defaults and applicability matching."""

from __future__ import annotations

from typing import Any

from .memory_models import MemoryApplicability, MemoryContextKind

_APPLICABILITY_KEYS = (
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
        return value
    if isinstance(value, dict):
        normalized = {
            key: _normalize_string_list(value.get(key))
            for key in _APPLICABILITY_KEYS
        }
        return MemoryApplicability(**normalized)
    return MemoryApplicability()


def normalize_trigger_task_types(value: Any) -> list[str]:
    """Normalize trigger_task_types while preserving unknown values for audit visibility."""
    normalized: list[str] = []
    for item in _normalize_string_list(value):
        lowered = item.lower()
        lowered = _TRIGGER_TASK_TYPE_ALIASES.get(lowered, lowered)
        if lowered not in normalized:
            normalized.append(lowered)
    return normalized


def normalize_trigger_phases(value: Any) -> list[str]:
    """Normalize trigger_phases into a compact, deduplicated list."""
    return [item.lower() for item in _normalize_string_list(value)]


def applicability_has_targets(value: MemoryApplicability | dict[str, Any] | None) -> bool:
    """Return True when applicability narrows the eligible audience."""
    resolved = normalize_applicability(value)
    return any(
        getattr(resolved, field_name)
        for field_name in (
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
            "exclude_consumer_profiles",
            "exclude_agent_slugs",
            "exclude_audience_tags",
        )
    )


def applicability_matches(
    applicability: MemoryApplicability | dict[str, Any] | None,
    *,
    consumer_profile: str | None = None,
    consumer_agent_slug: str | None = None,
    consumer_tags: list[str] | None = None,
) -> bool:
    """Return True when a memory applies to the current consumer."""
    resolved = normalize_applicability(applicability)
    tag_set = set(consumer_tags or [])

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
