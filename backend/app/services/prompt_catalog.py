"""Canonical prompt slugs used by runtime workflows and UI."""

from __future__ import annotations


def build_agent_system_prompt_slug(agent_slug: str) -> str:
    return f"{agent_slug}-system-prompt"


PLATFORM_CONTEXT_PROMPT_SLUG = "platform-context"

__all__ = [
    "PLATFORM_CONTEXT_PROMPT_SLUG",
    "build_agent_system_prompt_slug",
]
