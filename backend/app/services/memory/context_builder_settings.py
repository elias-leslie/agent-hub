"""Settings override logic for progressive context."""

from __future__ import annotations

from typing import Any

from .context_profiles import MemoryConsumerProfile
from .settings import MemorySettingsDTO

DEFAULT_AGENT_MEMORY_CONFIG: dict[str, Any] = {
    "injection_enabled": True,
    "project_index_enabled": True,
    "tool_capabilities_enabled": True,
    "include_mandates": True,
    "include_guardrails": True,
    "include_references": True,
    "reference_index_enabled": True,
    "continuity_enabled": True,
    "continuity_max_sessions": 5,
    "audience_tags": [],
    "exclude_tags": [],
    "exclude_memory_uuids": [],
}
_CANONICAL_BOOL_KEYS = (
    "injection_enabled",
    "project_index_enabled",
    "tool_capabilities_enabled",
    "include_mandates",
    "include_guardrails",
    "include_references",
    "reference_index_enabled",
    "continuity_enabled",
)
_CANONICAL_LIST_KEYS = ("audience_tags", "exclude_tags", "exclude_memory_uuids")
_CANONICAL_INT_DEFAULTS = {"continuity_max_sessions": 5}
_CANONICAL_PROFILE_KEYS = (
    "consumer_profile",
    "runtime_consumer_profile",
    "preview_consumer_profile",
)
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


def _normalize_consumer_profile_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        return MemoryConsumerProfile(cleaned).value
    except ValueError:
        return None


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
        and key not in _CANONICAL_PROFILE_KEYS
        and key not in _LEGACY_KEYS
    }
    enabled = _coerce_bool(raw.get("enabled"), True)
    injection_enabled = enabled and _coerce_bool(raw.get("injection_enabled"), True)
    normalized = {
        **extras,
        "injection_enabled": injection_enabled,
        "project_index_enabled": _coerce_bool(raw.get("project_index_enabled"), True),
        "tool_capabilities_enabled": _coerce_bool(raw.get("tool_capabilities_enabled"), True),
        "include_mandates": _coerce_bool(raw.get("include_mandates"), True),
        "include_guardrails": _coerce_bool(raw.get("include_guardrails"), True),
        "include_references": _coerce_bool(raw.get("include_references"), True),
        "reference_index_enabled": _coerce_bool(raw.get("reference_index_enabled"), True),
        "continuity_enabled": _coerce_bool(raw.get("continuity_enabled"), True),
        "continuity_max_sessions": _coerce_int(raw.get("continuity_max_sessions"), 5),
        "audience_tags": _normalize_string_list(raw.get("audience_tags")),
        "exclude_tags": _normalize_string_list(raw.get("exclude_tags")),
        "exclude_memory_uuids": _normalize_string_list(raw.get("exclude_memory_uuids")),
    }
    for key in _CANONICAL_PROFILE_KEYS:
        normalized_value = _normalize_consumer_profile_name(raw.get(key))
        if normalized_value is not None:
            normalized[key] = normalized_value
    if not injection_enabled:
        normalized["include_mandates"] = False
        normalized["include_guardrails"] = False
        normalized["include_references"] = False
        normalized["reference_index_enabled"] = False
        normalized["continuity_enabled"] = False
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
    return normalize_memory_config(inherited) or inherited


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


def resolve_project_index_enabled(
    memory_config: dict[str, Any] | None,
) -> bool:
    """Resolve whether compact project-index metadata is enabled for an agent."""
    normalized = normalize_memory_config(memory_config)
    if normalized is None:
        return True
    return bool(normalized.get("project_index_enabled", True))


def resolve_tool_capabilities_enabled(
    memory_config: dict[str, Any] | None,
) -> bool:
    """Resolve whether generated wrapper-tool capability context is enabled."""
    normalized = normalize_memory_config(memory_config)
    if normalized is None:
        return True
    return bool(normalized.get("tool_capabilities_enabled", True))


def resolve_runtime_prompt_includes(
    memory_config: dict[str, Any] | None,
) -> tuple[bool, bool]:
    """Resolve optional runtime prompt layers that track memory-config toggles."""
    if not memory_injection_enabled(memory_config):
        return False, False
    include_mandates, include_guardrails, _ = resolve_memory_config_includes(memory_config)
    return include_mandates, include_guardrails


def resolve_reference_index_enabled(
    memory_config: dict[str, Any] | None,
) -> bool:
    """Resolve whether passive reference index content is enabled for an agent."""
    normalized = normalize_memory_config(memory_config)
    if normalized is None:
        return True
    return bool(normalized.get("reference_index_enabled", True))


def resolve_continuity_settings(
    settings: MemorySettingsDTO,
    memory_config: dict[str, Any] | None,
) -> tuple[bool, int, bool, bool]:
    """Resolve continuity settings from custom config or global settings."""
    normalized = normalize_memory_config(memory_config)
    if normalized is None:
        return settings.continuity_enabled, settings.continuity_max_sessions, False, False
    return (
        normalized["continuity_enabled"],
        normalized["continuity_max_sessions"],
        _coerce_bool(normalized.get("cross_project_enabled"), False),
        _coerce_bool(normalized.get("live_sessions_enabled"), False),
    )


def resolve_memory_tags(memory_config: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    """Resolve audience and exclude tags from canonical agent memory config."""
    normalized = normalize_memory_config(memory_config)
    if normalized is None:
        return [], []
    return normalized["audience_tags"], normalized["exclude_tags"]


def resolve_excluded_memory_uuids(memory_config: dict[str, Any] | None) -> list[str]:
    """Resolve explicit per-agent memory UUID suppressions."""
    normalized = normalize_memory_config(memory_config)
    if normalized is None:
        return []
    return normalized["exclude_memory_uuids"]


def resolve_memory_consumer_profile(
    memory_config: dict[str, Any] | None,
    *,
    surface: str = "runtime",
) -> str | None:
    """Resolve the configured consumer profile for a delivery surface.

    Supported extension keys:
    - consumer_profile: shared default for runtime + preview
    - runtime_consumer_profile: runtime-only override
    - preview_consumer_profile: preview-only override
    """
    normalized = normalize_memory_config(memory_config)
    if normalized is None:
        return MemoryConsumerProfile.AGENT_PREVIEW.value if surface == "preview" else None

    if surface == "preview":
        preview_profile = _normalize_consumer_profile_name(
            normalized.get("preview_consumer_profile")
        )
        if preview_profile:
            return preview_profile

    runtime_profile = _normalize_consumer_profile_name(
        normalized.get("runtime_consumer_profile")
    )
    if runtime_profile:
        return runtime_profile

    shared_profile = _normalize_consumer_profile_name(normalized.get("consumer_profile"))
    if shared_profile:
        return shared_profile

    return MemoryConsumerProfile.AGENT_PREVIEW.value if surface == "preview" else None


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
