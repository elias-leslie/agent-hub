"""Shared persona policy wording and command checks."""

from __future__ import annotations

PERSONA_BLOCKED_BASH_SUBSTRINGS = (
    "git commit",
    "git push ",
)


def command_hits_persona_git_publish_policy(command: str) -> bool:
    """Return True when a command violates the persona git publish policy."""
    command_lower = command.lower().strip()
    return any(blocked in command_lower for blocked in PERSONA_BLOCKED_BASH_SUBSTRINGS)


def get_persona_git_publish_block_reason() -> str:
    """Return the canonical persona git-publish policy message."""
    return (
        "The persona must not use raw git commit/push from Bash. "
        "Use manage_tasks(action='smart_sync', project_id='...') for coherent publish debt, "
        "or the canonical commit.sh flow only when direct code intervention is operationally required."
    )
