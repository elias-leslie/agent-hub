"""Shared persona policy wording and command checks."""

from __future__ import annotations

PERSONA_BLOCKED_BASH_SUBSTRINGS = (
    "git commit",
    "git push ",
)
_MANAGED_WORKSPACE_ROOT = "/srv/workspaces/projects/"


def command_hits_persona_git_publish_policy(command: str) -> bool:
    """Return True when a command violates the persona git publish policy."""
    command_lower = command.lower().strip()
    return any(blocked in command_lower for blocked in PERSONA_BLOCKED_BASH_SUBSTRINGS)


def command_hits_persona_workspace_git_policy(command: str) -> bool:
    """Return True when persona inspects managed workspace repos with raw git in Bash."""
    normalized = " ".join(command.lower().split())
    if _MANAGED_WORKSPACE_ROOT not in normalized or "git " not in normalized:
        return False
    return (
        f"git -c {_MANAGED_WORKSPACE_ROOT}" in normalized
        or (f"cd {_MANAGED_WORKSPACE_ROOT}" in normalized and "&& git " in normalized)
    )


def get_persona_git_publish_block_reason() -> str:
    """Return the canonical persona git-publish policy message."""
    return (
        "The persona must not use raw git commit/push from Bash. "
        "Use the canonical commit.sh publish flow after validation when direct code "
        "intervention is operationally required."
    )


def get_persona_workspace_git_block_reason() -> str:
    """Return the canonical persona raw-workspace-git policy message."""
    return (
        "The persona must not inspect managed workspace repos with raw git via Bash. "
        "Use injected <git_state>, st pulse, st cleanup status --all, or st context instead."
    )
