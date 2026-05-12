"""Render <tool-usage> by delegating to `st tools manifest --format inject`.

The summitflow CLI owns the source of truth via @usage decorators on each
command. This module is a thin adapter for agent-hub's context-injection path.
Changing a command's policy in summitflow flows here on next render with no
duplicate state to maintain.
"""

from __future__ import annotations

import os
from functools import lru_cache

from app.utils.safe_subprocess import run_process

from .context_profiles import MemoryConsumerProfile, resolve_consumer_profile

_FRONTEND_TASK_TYPES = {"frontend", "ui-design", "design-review", "test", "verification"}
_RUNTIME_TASK_TYPES = {
    "backend", "frontend", "ui-design", "refactor", "bug-fix", "test",
    "performance", "config", "devops", "database", "exploration",
    "heartbeat", "wake", "review",
}
_GENERIC_TASK_TYPES = {None, "", "chat"}


def _profile_filters(
    consumer_profile: str | None,
    task_type: str | None,
) -> tuple[str | None, str | None]:
    """Decide whether to filter on task_type for the given consumer profile.

    Startup profile sees the full set; runtime profiles filter unless the task
    type is generic ("", "chat", None), matching the prior policy.
    """
    profile = resolve_consumer_profile(consumer_profile)
    if profile == MemoryConsumerProfile.AGENT_STARTUP:
        return (None, None)
    if task_type in _GENERIC_TASK_TYPES:
        return (None, None)
    if task_type not in _RUNTIME_TASK_TYPES and task_type not in _FRONTEND_TASK_TYPES:
        return (None, None)
    return (task_type, None)


def _density_for_context(consumer_profile: str | None, task_type: str | None) -> str:
    profile = resolve_consumer_profile(consumer_profile)
    if profile == MemoryConsumerProfile.AGENT_STARTUP:
        return "full"
    if task_type in _GENERIC_TASK_TYPES:
        return "core"
    if task_type in _RUNTIME_TASK_TYPES or task_type in _FRONTEND_TASK_TYPES:
        return "task"
    return "core"


@lru_cache(maxsize=64)
def _manifest_inject(
    task_type: str | None,
    agent_slug: str | None,
    consumer_profile: str | None,
    density: str,
) -> str:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    cmd = ["st", "tools", "manifest", "--format", "inject", "--density", density]
    if task_type:
        cmd += ["--task", task_type]
    if agent_slug:
        cmd += ["--agent", agent_slug]
    if consumer_profile:
        cmd += ["--profile", consumer_profile]
    try:
        result = run_process(cmd, capture_output=True, text=True, timeout=5, check=False, env=env)
    except Exception:
        return ""
    return (result.stdout or "").strip()


def format_tool_capability_context(
    *,
    consumer_profile: str | None,
    task_type: str | None = None,
    project_id: str | None = None,
    bash_available: bool | None = None,
    agent_slug: str | None = None,
) -> str:
    """Render the <tool-usage> block by calling `st tools manifest --format inject`."""
    if agent_slug == "persona" and bash_available is not True:
        return ""
    if bash_available is False:
        return ""
    effective_task, _ = _profile_filters(consumer_profile, task_type)
    density = _density_for_context(consumer_profile, task_type)
    body = _manifest_inject(effective_task, agent_slug, consumer_profile, density)
    if not body:
        return ""
    return f"<tool-usage>\n{body}\n</tool-usage>"


def build_tool_capability_payload(
    *,
    consumer_profile: str | None,
    task_type: str | None = None,
    project_id: str | None = None,
    bash_available: bool | None = None,
    agent_slug: str | None = None,
) -> dict | None:
    """Back-compat: emit a single-field dict wrapping the inject body."""
    body = format_tool_capability_context(
        consumer_profile=consumer_profile,
        task_type=task_type,
        project_id=project_id,
        bash_available=bash_available,
        agent_slug=agent_slug,
    )
    if not body:
        return None
    return {"tool_usage": body}
