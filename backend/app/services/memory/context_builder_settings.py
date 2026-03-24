"""Settings override logic for progressive context."""

from __future__ import annotations

from typing import Any

from .settings import MemorySettingsDTO

DEFAULT_AGENT_MEMORY_CONFIG: dict[str, Any] = {
    "injection_enabled": True,
    "include_mandates": True,
    "include_guardrails": True,
    "include_references": True,
    "continuity_enabled": True,
    "continuity_max_sessions": 5,
    "audience_tags": [],
    "exclude_tags": [],
}
_CANONICAL_BOOL_KEYS = (
    "injection_enabled",
    "include_mandates",
    "include_guardrails",
    "include_references",
    "continuity_enabled",
)
_CANONICAL_LIST_KEYS = ("audience_tags", "exclude_tags")
_CANONICAL_INT_DEFAULTS = {"continuity_max_sessions": 5}
_LEGACY_KEYS = {"enabled"}


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    return default


def _coerce_int(value: Any, default: int, *, minimum: int = 1) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return max(value, minimum)
    return default


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


def default_agent_memory_config() -> dict[str, Any]:
    """Return the canonical per-agent memory config defaults."""
    return {
        key: list(value) if isinstance(value, list) else value
        for key, value in DEFAULT_AGENT_MEMORY_CONFIG.items()
    }


def normalize_memory_config(memory_config: dict[str, Any] | None) -> dict[str, Any] | None:
    """Normalize stored agent memory config to a full canonical shape.

    `None` means the agent inherits global defaults. Any non-null config is
    treated as an explicit custom config and returned with all core fields
    materialized plus unknown extension keys preserved.
    """
    if memory_config is None:
        return None

    raw = dict(memory_config)
    extras = {
        key: value
        for key, value in raw.items()
        if key not in _CANONICAL_BOOL_KEYS
        and key not in _CANONICAL_LIST_KEYS
        and key not in _CANONICAL_INT_DEFAULTS
        and key not in _LEGACY_KEYS
    }
    enabled = _coerce_bool(raw.get("enabled"), True)
    normalized = {
        **extras,
        "injection_enabled": enabled and _coerce_bool(raw.get("injection_enabled"), True),
        "include_mandates": _coerce_bool(raw.get("include_mandates"), True),
        "include_guardrails": _coerce_bool(raw.get("include_guardrails"), True),
        "include_references": _coerce_bool(raw.get("include_references"), True),
        "continuity_enabled": _coerce_bool(raw.get("continuity_enabled"), True),
        "continuity_max_sessions": _coerce_int(raw.get("continuity_max_sessions"), 5),
        "audience_tags": _normalize_string_list(raw.get("audience_tags")),
        "exclude_tags": _normalize_string_list(raw.get("exclude_tags")),
    }
    return normalized


def resolve_effective_memory_config(
    settings: MemorySettingsDTO,
    memory_config: dict[str, Any] | None,
) -> dict[str, Any]:
    """Resolve the full effective agent memory config after inheritance.

    `memory_config=None` means the agent inherits global memory settings plus
    the canonical per-agent defaults for non-global fields.
    """
    normalized = normalize_memory_config(memory_config)
    if normalized is not None:
        return dict(normalized)

    inherited = default_agent_memory_config()
    inherited["injection_enabled"] = settings.enabled
    inherited["continuity_enabled"] = settings.continuity_enabled
    inherited["continuity_max_sessions"] = settings.continuity_max_sessions
    return inherited


def memory_injection_enabled(memory_config: dict[str, Any] | None) -> bool:
    """Resolve whether runtime memory-related injection is enabled for an agent."""
    normalized = normalize_memory_config(memory_config)
    if normalized is None:
        return True
    return normalized["injection_enabled"]


def resolve_memory_config_includes(
    memory_config: dict[str, Any] | None,
) -> tuple[bool, bool, bool]:
    """Resolve per-agent include flags with runtime defaults."""
    normalized = normalize_memory_config(memory_config)
    if normalized is None:
        return True, True, True
    return (
        normalized["include_mandates"],
        normalized["include_guardrails"],
        normalized["include_references"],
    )


def resolve_runtime_prompt_includes(
    memory_config: dict[str, Any] | None,
) -> tuple[bool, bool]:
    """Resolve optional runtime prompt layers that track memory-config toggles."""
    if not memory_injection_enabled(memory_config):
        return False, False
    include_mandates, include_guardrails, _ = resolve_memory_config_includes(memory_config)
    return include_mandates, include_guardrails


def resolve_continuity_settings(
    settings: MemorySettingsDTO,
    memory_config: dict[str, Any] | None,
) -> tuple[bool, int, bool, bool]:
    """Resolve continuity settings from custom config or global settings."""
    normalized = normalize_memory_config(memory_config)
    if normalized is None:
        return settings.continuity_enabled, settings.continuity_max_sessions, True, False
    return (
        normalized["continuity_enabled"],
        normalized["continuity_max_sessions"],
        _coerce_bool(normalized.get("cross_project_enabled"), True),
        _coerce_bool(normalized.get("live_sessions_enabled"), False),
    )


def resolve_memory_tags(memory_config: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    """Resolve audience and exclude tags from canonical agent memory config."""
    normalized = normalize_memory_config(memory_config)
    if normalized is None:
        return [], []
    return normalized["audience_tags"], normalized["exclude_tags"]


def apply_memory_config_overrides(
    settings: MemorySettingsDTO,
    memory_config: dict[str, Any] | None,
) -> None:
    """Apply memory_config overrides to settings in-place.

    Args:
        settings: MemorySettingsDTO object to modify
        memory_config: Optional config dict from agent/request
    """
    normalized = normalize_memory_config(memory_config)
    if normalized is None:
        return

    settings.enabled = normalized["injection_enabled"]
