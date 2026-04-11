"""Consumer-specific progressive-context rendering profiles."""

from __future__ import annotations

from enum import StrEnum

CODEX_STARTUP_FULL_TAG = "codex_startup_full"


class MemoryConsumerProfile(StrEnum):
    """Supported delivery profiles for injected memory context."""

    AGENT_RUNTIME = "agent_runtime"
    AGENT_PREVIEW = "agent_preview"
    CLAUDE_SESSION_START = "claude_session_start"
    CODEX_STARTUP = "codex_startup"


_STARTUP_MAX_MANDATES = 28
_STARTUP_MAX_GUARDRAILS = 6


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


def startup_limits_for_profile(consumer_profile: str | None) -> tuple[int, int]:
    """Return mandate/guardrail caps for startup-style consumers."""
    profile = resolve_consumer_profile(consumer_profile)
    if profile in {
        MemoryConsumerProfile.CODEX_STARTUP,
        MemoryConsumerProfile.CLAUDE_SESSION_START,
    }:
        return (_STARTUP_MAX_MANDATES, _STARTUP_MAX_GUARDRAILS)
    return (0, 0)
