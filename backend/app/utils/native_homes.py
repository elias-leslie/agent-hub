"""Where native CLI runtimes keep their transcripts, across every user that runs agents.

Agents run as a separate user, so Codex rollouts and Claude Code transcripts live under more than one
home. ``AGENT_HUB_NATIVE_HOMES`` (os.pathsep-separated) replaces the default list; the per-runtime knobs
``AGENT_HUB_CODEX_SESSIONS`` / ``AGENT_HUB_CLAUDE_PROJECTS`` take one path (as before) or several.

Agents on a remote agent host write their transcripts on that host; Agent Hub keeps a copy of each under
``<host homes>/<host name>``, laid out like the host's home (``app.services.remote_host_sessions``). Every
such directory counts as a native home, so its transcripts are read exactly like local ones.
``AGENT_HUB_HOST_HOMES`` moves the host homes.
"""

from __future__ import annotations

import os
from pathlib import Path

# Readable (ACL) by the service user; a missing home is simply skipped by every reader.
DEFAULT_AGENT_HOMES = ("/home/agent",)
DEFAULT_HOST_HOMES = "~/.local/state/agent-hub/host-homes"


def _paths(raw: str) -> list[Path]:
    return [Path(part).expanduser() for part in raw.split(os.pathsep) if part.strip()]


def host_homes_root() -> Path:
    return Path(os.environ.get("AGENT_HUB_HOST_HOMES") or DEFAULT_HOST_HOMES).expanduser()


def host_homes() -> list[Path]:
    """One native home per remote host that has sent a transcript."""
    root = host_homes_root()
    try:
        return sorted(path for path in root.iterdir() if path.is_dir() and not path.is_symlink())
    except OSError:
        return []


def native_homes() -> list[Path]:
    if configured := os.environ.get("AGENT_HUB_NATIVE_HOMES"):
        return _paths(configured)
    return [Path.home(), *map(Path, DEFAULT_AGENT_HOMES), *host_homes()]


def _roots(env_name: str, *relative: str) -> list[Path]:
    if configured := os.environ.get(env_name):
        return _paths(configured)
    return [home.joinpath(*relative) for home in native_homes()]


def codex_session_roots() -> list[Path]:
    return _roots("AGENT_HUB_CODEX_SESSIONS", ".codex", "sessions")


def claude_project_roots() -> list[Path]:
    return _roots("AGENT_HUB_CLAUDE_PROJECTS", ".claude", "projects")


def pi_session_roots() -> list[Path]:
    return _roots("AGENT_HUB_PI_SESSIONS", ".pi", "agent", "sessions")
