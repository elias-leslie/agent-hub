"""Where native CLI runtimes keep their transcripts, across every user that runs agents.

Agents run as a separate user, so Codex rollouts and Claude Code transcripts live under more than one
home. ``AGENT_HUB_NATIVE_HOMES`` (os.pathsep-separated) replaces the default list; the per-runtime knobs
``AGENT_HUB_CODEX_SESSIONS`` / ``AGENT_HUB_CLAUDE_PROJECTS`` take one path (as before) or several.
"""

from __future__ import annotations

import os
from pathlib import Path

# Readable (ACL) by the service user; a missing home is simply skipped by every reader.
DEFAULT_AGENT_HOMES = ("/home/agent",)


def _paths(raw: str) -> list[Path]:
    return [Path(part).expanduser() for part in raw.split(os.pathsep) if part.strip()]


def native_homes() -> list[Path]:
    if configured := os.environ.get("AGENT_HUB_NATIVE_HOMES"):
        return _paths(configured)
    return [Path.home(), *map(Path, DEFAULT_AGENT_HOMES)]


def _roots(env_name: str, *relative: str) -> list[Path]:
    if configured := os.environ.get(env_name):
        return _paths(configured)
    return [home.joinpath(*relative) for home in native_homes()]


def codex_session_roots() -> list[Path]:
    return _roots("AGENT_HUB_CODEX_SESSIONS", ".codex", "sessions")


def claude_project_roots() -> list[Path]:
    return _roots("AGENT_HUB_CLAUDE_PROJECTS", ".claude", "projects")
