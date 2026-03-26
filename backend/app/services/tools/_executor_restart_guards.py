"""Restart-guard helpers for the direct tool executor.

Detects and blocks dangerous in-band Agent Hub restart and self-hosting
worker restart commands before they reach the shell.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

_AGENT_HUB_DEFAULT_RESTART_WORKERS = frozenset({
    "agent-hub-hatchet-ops-worker.service",
})
_AGENT_HUB_ALL_RESTART_WORKERS = frozenset({
    *_AGENT_HUB_DEFAULT_RESTART_WORKERS,
    "agent-hub-hatchet-agent-worker.service",
})
_DIRECT_SYSTEMCTL_SERVICE_RE = re.compile(
    r"(^|[;&|]\s*)(?:sudo\s+)?systemctl\s+(?:--user\s+)?"
    r"(?:restart|stop|start|kill|try-restart|reload-or-restart)\s+(?P<unit>\S+)",
)
_SHELL_SEPARATOR_TOKENS = frozenset({"&&", "||", ";", "|", "&"})
_RESTART_SCRIPT_BASENAMES = frozenset({"rebuild.sh", "restart.sh"})


def _normalize_shell_command(command: str) -> str:
    return re.sub(r"\s+", " ", command.strip().lower())


def _split_shell_segments(command: str) -> list[list[str]]:
    """Split a shell command into tokenized segments around common separators."""
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.split()

    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in _SHELL_SEPARATOR_TOKENS:
            if current:
                segments.append(current)
                current = []
            continue
        current.append(token)
    if current:
        segments.append(current)
    return segments


def _in_band_agent_hub_restart_block_reason(command: str) -> str | None:
    """Block plain Agent Hub rebuild/restart inside the Agent Hub control plane."""
    for segment in _split_shell_segments(command):
        if not segment:
            continue

        script_index = 0
        if Path(segment[0]).name.lower() == "bash":
            if len(segment) < 2:
                continue
            script_index = 1

        script_name = Path(segment[script_index]).name.lower()
        if script_name not in _RESTART_SCRIPT_BASENAMES:
            continue

        args = segment[script_index + 1:]
        if any(arg in {"--help", "-h", "--status"} for arg in args):
            continue

        positional = [arg.lower() for arg in args if not arg.startswith("-")]
        if not positional or positional[0] != "agent-hub":
            continue

        if "--detach" in args:
            continue

        return (
            "Do not restart the Agent Hub control plane from inside an active Agent Hub session. "
            "Use `rebuild.sh --detach agent-hub` (or `restart.sh --detach agent-hub`) to queue "
            "the canonical rebuild out-of-band, then verify from a fresh session after restart."
        )

    return None


def _rewrite_in_band_agent_hub_restart(command: str) -> tuple[str, str] | None:
    """Canonicalize simple Agent Hub self-restarts to detached rebuilds."""
    segments = _split_shell_segments(command)
    if len(segments) != 1:
        return None

    segment = segments[0]
    if not segment:
        return None

    script_index = 0
    if Path(segment[0]).name.lower() == "bash":
        if len(segment) < 2:
            return None
        script_index = 1

    script_name = Path(segment[script_index]).name.lower()
    if script_name not in _RESTART_SCRIPT_BASENAMES:
        return None

    args = segment[script_index + 1:]
    if any(arg in {"--help", "-h", "--status", "--detach"} for arg in args):
        return None

    positional = [arg.lower() for arg in args if not arg.startswith("-")]
    if positional != ["agent-hub"]:
        return None

    rewritten = list(segment)
    rewritten.insert(script_index + 1, "--detach")
    rewritten_command = shlex.join(rewritten)
    return (
        rewritten_command,
        f"Command auto-detached for runtime safety. Running `{rewritten_command}` instead.",
    )


def _self_hosting_restart_block_reason(command: str, env: dict[str, str]) -> str | None:
    """Return a block reason when a command would restart its hosting worker."""
    host_service = env.get("AGENT_HUB_HOST_SERVICE", "").strip().lower()
    if not host_service:
        return None

    normalized = _normalize_shell_command(command)
    systemctl_match = _DIRECT_SYSTEMCTL_SERVICE_RE.search(normalized)
    if systemctl_match and systemctl_match.group("unit").lower() == host_service:
        return (
            f"Do not restart the hosting worker service ({host_service}) from inside the active "
            "session. Run that restart from outside the worker after the current work is drained."
        )

    is_agent_hub_rebuild = (
        "agent-hub" in normalized
        and ("rebuild.sh" in normalized or "restart.sh" in normalized)
    )
    if not is_agent_hub_rebuild:
        return None

    restarted_workers = (
        _AGENT_HUB_ALL_RESTART_WORKERS
        if "--include-all-workers" in normalized
        else _AGENT_HUB_DEFAULT_RESTART_WORKERS
    )
    if host_service not in restarted_workers:
        return None

    if "--include-all-workers" in normalized:
        return (
            f"`rebuild.sh agent-hub --include-all-workers` would restart the hosting worker service "
            f"({host_service}). Use `rebuild.sh agent-hub` for safe backend/frontend + ops rebuilds, "
            "and restart the agent worker separately from outside active execution."
        )

    return (
        f"`rebuild.sh agent-hub` would restart the hosting worker service ({host_service}). "
        "Run it from outside the active worker so the current execution is not terminated mid-task."
    )
