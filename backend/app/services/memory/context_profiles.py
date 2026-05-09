"""Consumer-specific progressive-context rendering profiles."""

from __future__ import annotations

from enum import StrEnum

CODEX_STARTUP_FULL_TAG = "codex_startup_full"


class MemoryConsumerProfile(StrEnum):
    """Supported delivery profiles for injected memory context."""

    AGENT_RUNTIME = "agent_runtime"
    AGENT_PREVIEW = "agent_preview"
    AGENT_GENERAL = "agent_general"
    AGENT_VISUAL = "agent_visual"
    AGENT_CODING = "agent_coding"
    AGENT_OPERATOR = "agent_operator"
    AGENT_PROMPTOPS = "agent_promptops"
    CLAUDE_SESSION_START = "claude_session_start"
    CODEX_STARTUP = "codex_startup"
    GEMINI_STARTUP = "gemini_startup"


_PROFILE_POLICY_LIMITS: dict[MemoryConsumerProfile, tuple[int, int]] = {
    MemoryConsumerProfile.AGENT_PREVIEW: (8, 2),
    MemoryConsumerProfile.AGENT_GENERAL: (6, 2),
    MemoryConsumerProfile.AGENT_VISUAL: (6, 2),
    MemoryConsumerProfile.AGENT_CODING: (16, 4),
    MemoryConsumerProfile.AGENT_OPERATOR: (20, 6),
    MemoryConsumerProfile.AGENT_PROMPTOPS: (14, 4),
    MemoryConsumerProfile.CLAUDE_SESSION_START: (8, 2),
    MemoryConsumerProfile.CODEX_STARTUP: (28, 6),
    MemoryConsumerProfile.GEMINI_STARTUP: (8, 2),
}
_PROFILE_QUERY_REFERENCE_DEFAULTS: dict[MemoryConsumerProfile, bool] = {
    MemoryConsumerProfile.AGENT_PREVIEW: False,
    MemoryConsumerProfile.AGENT_GENERAL: False,
    MemoryConsumerProfile.AGENT_VISUAL: False,
    MemoryConsumerProfile.AGENT_CODING: True,
    MemoryConsumerProfile.AGENT_OPERATOR: True,
    MemoryConsumerProfile.AGENT_PROMPTOPS: True,
    MemoryConsumerProfile.CLAUDE_SESSION_START: False,
    MemoryConsumerProfile.CODEX_STARTUP: False,
    MemoryConsumerProfile.GEMINI_STARTUP: False,
}


def resolve_consumer_profile(consumer_profile: str | None) -> MemoryConsumerProfile:
    """Normalize caller-provided profile names to a known profile."""
    if not consumer_profile:
        return MemoryConsumerProfile.AGENT_RUNTIME
    try:
        return MemoryConsumerProfile(consumer_profile)
    except ValueError:
        return MemoryConsumerProfile.AGENT_RUNTIME


def full_render_tags_for_profile(consumer_profile: str | None) -> set[str]:
    """Return memory tags that should render at full detail for a profile."""
    profile = resolve_consumer_profile(consumer_profile)
    if profile == MemoryConsumerProfile.CODEX_STARTUP:
        return {CODEX_STARTUP_FULL_TAG}
    return set()


def priority_tags_for_profile(consumer_profile: str | None) -> set[str]:
    """Return memory tags that should be surfaced first for a profile."""
    return full_render_tags_for_profile(consumer_profile)


def policy_limits_for_profile(consumer_profile: str | None) -> tuple[int, int]:
    """Return mandate/guardrail caps for any policy-summary consumer."""
    profile = resolve_consumer_profile(consumer_profile)
    return _PROFILE_POLICY_LIMITS.get(profile, (0, 0))


def summarize_policies_for_profile(consumer_profile: str | None) -> bool:
    """Return True when mandates/guardrails should render as compact summaries."""
    profile = resolve_consumer_profile(consumer_profile)
    return profile in _PROFILE_POLICY_LIMITS


def startup_limits_for_profile(consumer_profile: str | None) -> tuple[int, int]:
    """Backward-compatible alias for older callers/tests."""
    return policy_limits_for_profile(consumer_profile)


def query_reference_selection_default_for_profile(consumer_profile: str | None) -> bool | None:
    """Return default semantic-reference behavior for a consumer profile.

    `None` means caller should use legacy fallback behavior.
    """
    profile = resolve_consumer_profile(consumer_profile)
    return _PROFILE_QUERY_REFERENCE_DEFAULTS.get(profile)
