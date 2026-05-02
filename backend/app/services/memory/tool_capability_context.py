"""Render compact wrapper-tool capability context from live CLI help output."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from subprocess import run
from typing import Any

import yaml

from .context_profiles import MemoryConsumerProfile, resolve_consumer_profile

_FRONTEND_TOOL_TASK_TYPES = {"frontend", "ui-design", "design-review", "test", "verification"}
_RUNTIME_TOOL_TASK_TYPES = {
    "backend", "frontend", "ui-design", "refactor", "bug-fix", "test",
    "performance", "config", "devops", "database", "exploration",
    "heartbeat", "wake", "review",
}
_GENERIC_DESCRIPTION_HEADINGS = {"available projects:"}


@dataclass(frozen=True)
class _ToolCapabilitySpec:
    name: str
    help_command: tuple[str, ...]
    fallback_description: str
    command_allowlist: tuple[str, ...] = ()
    flag_allowlist: tuple[str, ...] = ()
    runtime: bool = True
    startup: bool = True
    require_project: bool = False
    frontend_only: bool = False


_TOOL_SPECS: tuple[_ToolCapabilitySpec, ...] = (
    _ToolCapabilitySpec(
        name="st",
        help_command=("st", "--help"),
        fallback_description="SummitFlow CLI",
        command_allowlist=(
            "list", "ready", "ready-all", "context", "create", "claim",
            "done", "abandon", "cancel", "pause", "resume", "log",
            "search", "memory", "prompt", "feedback", "session-events",
            "sessions", "pulse", "cleanup", "persona", "agents", "complete",
            "autocode", "check", "db", "browser", "web", "service", "tools",
            "graph", "commit", "jj", "vcs", "backup", "vm",
        ),
    ),
    _ToolCapabilitySpec(
        name="db",
        help_command=("db", "--help"),
        fallback_description="Database CLI",
        command_allowlist=("tables", "schema", "query", "exec", "migrate status", "migrate upgrade"),
    ),
    _ToolCapabilitySpec(
        name="web-research",
        help_command=("web-research", "--help"),
        fallback_description="Shared public-web lookup wrapper",
        command_allowlist=("search", "research", "fetch"),
    ),
    _ToolCapabilitySpec(
        name="rebuild.sh",
        help_command=("rebuild.sh", "--help"),
        fallback_description="Project rebuild helper",
        flag_allowlist=("--detach", "--include-all-workers"),
        require_project=True,
    ),
)


def _matches_task_filter(task_type: str | None, *, frontend_only: bool) -> bool:
    if not frontend_only:
        return True
    return task_type in _FRONTEND_TOOL_TASK_TYPES


def _should_include_tool(
    spec: _ToolCapabilitySpec,
    *,
    consumer_profile: str | None,
    task_type: str | None,
    project_id: str | None,
) -> bool:
    profile = resolve_consumer_profile(consumer_profile)
    if profile in {
        MemoryConsumerProfile.CODEX_STARTUP,
        MemoryConsumerProfile.CLAUDE_SESSION_START,
    }:
        return spec.startup and _matches_task_filter(task_type, frontend_only=spec.frontend_only)
    if not spec.runtime:
        return False
    if spec.require_project and not project_id:
        return False
    if task_type in {None, "", "chat"}:
        return _matches_task_filter(task_type, frontend_only=spec.frontend_only)
    if task_type and task_type not in _RUNTIME_TOOL_TASK_TYPES and not spec.frontend_only:
        return False
    return _matches_task_filter(task_type, frontend_only=spec.frontend_only)


@lru_cache(maxsize=32)
def _read_help_output(command: tuple[str, ...]) -> str:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    try:
        result = run(command, capture_output=True, text=True, timeout=3, check=False, env=env)
    except Exception:
        return ""
    output = (result.stdout or "").strip()
    if output:
        return output
    stderr = (result.stderr or "").strip()
    if stderr and _looks_like_help_text(stderr) and not _looks_like_error_text(stderr):
        return stderr
    return ""


def _looks_like_help_text(text: str) -> bool:
    lowered_lines = [line.strip().lower() for line in text.splitlines() if line.strip()]
    return any(
        line.startswith("usage:")
        or line == "commands:"
        or line == "options:"
        or line == "positional arguments:"
        or line.startswith("subcommands")
        for line in lowered_lines
    )


def _looks_like_error_text(text: str) -> bool:
    lowered_lines = [line.strip().lower() for line in text.splitlines() if line.strip()]
    return any(
        line.startswith("traceback (most recent call last):")
        or "modulenotfounderror:" in line
        or "exception:" in line
        or "error:" in line
        for line in lowered_lines
    )


def _description_from_help(help_text: str, fallback: str) -> str:
    for raw_line in help_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lowered = line.lower()
        if lowered.startswith("usage:"):
            continue
        if lowered.endswith("commands:") or lowered.endswith("options:"):
            continue
        if lowered in _GENERIC_DESCRIPTION_HEADINGS:
            continue
        return line
    return fallback


def _extract_help_lines(help_text: str) -> list[str]:
    return [line.rstrip() for line in help_text.splitlines()]


def _extract_st_commands(help_text: str) -> list[str]:
    commands: list[str] = []
    in_commands = False
    for raw_line in _extract_help_lines(help_text):
        stripped = raw_line.strip()
        if stripped == "Commands:":
            in_commands = True
            continue
        if not in_commands:
            continue
        if not raw_line.startswith("  "):
            break
        if not stripped:
            continue
        command = stripped.split()[0]
        if command and command not in commands:
            commands.append(command)
    return commands


def _extract_db_commands(help_text: str) -> list[str]:
    commands: list[str] = []
    section = ""
    for raw_line in _extract_help_lines(help_text):
        stripped = raw_line.strip()
        if stripped in {"Commands:", "Migration Commands:", "Dump Commands:"}:
            section = stripped
            continue
        if section and not stripped:
            continue
        if section and raw_line.startswith("  "):
            left = raw_line.strip()
            command = left.split("  ")[0].strip()
            if command and command not in commands:
                commands.append(command)
    return commands


def _extract_web_research_commands(help_text: str) -> list[str]:
    commands: list[str] = []
    in_positional = False
    for raw_line in _extract_help_lines(help_text):
        stripped = raw_line.strip()
        if stripped == "positional arguments:":
            in_positional = True
            continue
        if in_positional and stripped == "options:":
            break
        if in_positional and raw_line.startswith("    "):
            command = stripped.split()[0]
            if command.startswith("{"):
                continue
            if command and command not in commands:
                commands.append(command)
    return commands


def _extract_rebuild_flags(help_text: str) -> list[str]:
    usage_line = next((line.strip() for line in help_text.splitlines() if line.strip().startswith("Usage:")), "")
    flags: list[str] = []
    for token in usage_line.split():
        if token.startswith("[--") and token.endswith("]"):
            flags.append(token[1:-1])
    return flags


def _build_tool_entry(
    spec: _ToolCapabilitySpec,
    *,
    st_quick: list[str] | None = None,
) -> dict[str, Any] | None:
    help_text = _read_help_output(spec.help_command)
    if not help_text:
        return None

    commands: list[str] = []
    flags: list[str] = []
    if spec.name == "st":
        commands = _extract_st_commands(help_text)
    elif spec.name == "db":
        commands = _extract_db_commands(help_text)
    elif spec.name == "web-research":
        commands = _extract_web_research_commands(help_text)
    elif spec.name == "rebuild.sh":
        flags = _extract_rebuild_flags(help_text)

    filtered_commands = [
        command for command in spec.command_allowlist if command in commands
    ]
    filtered_flags = [flag for flag in spec.flag_allowlist if flag in flags]

    entry: dict[str, Any] = {
        "tool": spec.name,
        "purpose": _description_from_help(help_text, spec.fallback_description),
        "discover": " ".join(spec.help_command),
    }
    if filtered_commands:
        entry["commands"] = filtered_commands
    if filtered_flags:
        entry["flags"] = filtered_flags
    if spec.name == "st" and st_quick:
        entry["quick"] = st_quick
    return entry


def build_tool_capability_payload(
    *,
    consumer_profile: str | None,
    task_type: str | None = None,
    project_id: str | None = None,
    bash_available: bool | None = None,
    st_quick: list[str] | None = None,
) -> dict[str, Any] | None:
    if bash_available is False:
        return None

    tools: list[dict[str, Any]] = []
    for spec in _TOOL_SPECS:
        if not _should_include_tool(
            spec,
            consumer_profile=consumer_profile,
            task_type=task_type,
            project_id=project_id,
        ):
            continue
        entry = _build_tool_entry(spec, st_quick=st_quick)
        if entry is not None:
            tools.append(entry)

    if not tools:
        return None
    return {"tools": tools}


def format_tool_capability_context(
    *,
    consumer_profile: str | None,
    task_type: str | None = None,
    project_id: str | None = None,
    bash_available: bool | None = None,
    st_quick: list[str] | None = None,
) -> str:
    payload = build_tool_capability_payload(
        consumer_profile=consumer_profile,
        task_type=task_type,
        project_id=project_id,
        bash_available=bash_available,
        st_quick=st_quick,
    )
    if not payload:
        return ""
    compact_yaml = yaml.safe_dump(payload, default_flow_style=False, sort_keys=False).strip()
    if not compact_yaml:
        return ""
    return f"<tool-capabilities>\n{compact_yaml}\n</tool-capabilities>"
