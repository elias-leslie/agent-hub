"""Shared state dataclasses and constants for heartbeat data assembly."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from app.services.git_status_summary import RepoGitStatus
from app.services.ownership_lanes import STALE_WORKSTREAM_IDLE_MINUTES

if TYPE_CHECKING:
    pass

# Session staleness thresholds
_WORKSTREAM_LOOKBACK_HOURS = 24
_STALE_ACTIVE_MINUTES = STALE_WORKSTREAM_IDLE_MINUTES
_ACTIVE_SPECIALIST_LOOKBACK_HOURS = 6
_ACTIVE_SESSION_LOOKBACK_HOURS = 24
_ACTIVE_SESSION_GHOST_MINUTES = 15
_ACTIVE_SESSION_DISPLAY_LIMIT = 5
_ACTIVE_SESSION_PREFILTER_LIMIT = 25
_DEFAULT_SESSION_STALE_MINUTES = 15
_CODING_AGENT_SESSION_STALE_MINUTES = 30

# External ID prefixes for benchmark filtering
_BENCHMARK_EXTERNAL_ID_PREFIXES = (
    "benchmark:",
    "agent-output-benchmark:",
    "persona-benchmark:",
)

# Regex patterns
_STALE_READY_ALL_LINE = re.compile(r"^\s+\?\s+(task-[^\s]+).*\[stale-running\]$")
_COMPACT_STALE_LINE = re.compile(r"^- (?P<project>[a-z0-9-]+) \| (?P<task_id>task-[^\s|]+) \| ")
_TASK_ID_PATTERN = re.compile(r"\btask-[a-z0-9]+\b")

_WORKSPACE_BASE = Path("/srv/workspaces/projects")
_SUMMITFLOW_PROJECT_ID = "summitflow"


@dataclass(frozen=True)
class SummitFlowHeartbeatState:
    """Canonical SummitFlow truth bundle for one heartbeat assembly pass."""

    task_overview_response: dict[str, object] | None
    cleanup_status_response: dict[str, object] | None
    git_status_rows: list[RepoGitStatus]
    recent_failed_tasks: list[dict[str, object]]

    @property
    def task_overview_payload(self) -> dict[str, object] | None:
        if not isinstance(self.task_overview_response, dict):
            return None
        payload: object = self.task_overview_response.get("payload")
        if not isinstance(payload, dict):
            return None
        return payload  # type: ignore[return-value]

    @property
    def task_overview_raw(self) -> str:
        if not isinstance(self.task_overview_response, dict):
            return ""
        raw = self.task_overview_response.get("raw")
        return raw.strip() if isinstance(raw, str) else ""


@dataclass(frozen=True)
class AgentHubHeartbeatState:
    """Canonical Agent Hub truth bundle for one heartbeat assembly pass."""

    collected_at: datetime
    active_sessions: list[dict[str, object]]
    active_specialist_sessions: list[dict[str, object]]
    workstream_rows: list[dict[str, object]]
