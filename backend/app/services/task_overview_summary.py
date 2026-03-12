"""Helpers for summarizing `st ready-all` output for agentic consumers."""

from __future__ import annotations

import re
from dataclasses import dataclass

_SUMMARY_RE = re.compile(
    r"^READY-ALL\[(?P<ready>\d+) ready, (?P<blocked>\d+) blocked, "
    r"(?P<active>\d+) active, (?P<stale>\d+) stale across (?P<projects>\d+) projects\]$"
)
_PROJECT_RE = re.compile(r"^(?P<project>[a-z0-9-]+) \((?P<label>.+)\)$")
_TASK_RE = re.compile(
    r"^\s+(?P<prefix>[*!~? ])\s(?P<task_id>task-[^\s]+)\s+P(?P<priority>\d+)\s+"
    r"(?P<task_type>\S+)\s+\[(?P<mode>[AM])\]\s+(?P<title>.+?)(?: \[(?P<suffix>[^\]]+)])?$"
)


@dataclass(frozen=True)
class TaskOverviewStats:
    """Parsed headline counts from a ready-all overview."""

    ready: int = 0
    blocked: int = 0
    active: int = 0
    stale: int = 0
    projects: int = 0


@dataclass(frozen=True)
class ReadyTaskCandidate:
    """Executable ready task surfaced from ready-all output."""

    project_id: str
    task_id: str
    priority: int
    task_type: str
    mode: str
    title: str


@dataclass(frozen=True)
class ProjectOverview:
    """Compact per-project summary row parsed from ready-all output."""

    project_id: str
    label: str


def parse_task_overview_stats(task_overview: str) -> TaskOverviewStats:
    """Parse the READY-ALL headline counts from compact CLI output."""
    first_line = task_overview.strip().splitlines()[0] if task_overview.strip() else ""
    match = _SUMMARY_RE.match(first_line)
    if not match:
        return TaskOverviewStats()
    return TaskOverviewStats(
        ready=int(match.group("ready")),
        blocked=int(match.group("blocked")),
        active=int(match.group("active")),
        stale=int(match.group("stale")),
        projects=int(match.group("projects")),
    )


def extract_ready_task_candidates(
    task_overview: str,
    *,
    per_project_limit: int = 2,
) -> list[ReadyTaskCandidate]:
    """Extract executable ready tasks from ready-all output.

    Only plain ready rows and ready bug rows (`*`) are included. Active, blocked, and
    stale rows are excluded.
    """
    candidates: list[ReadyTaskCandidate] = []
    current_project: str | None = None
    project_counts: dict[str, int] = {}

    for raw_line in task_overview.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        project_match = _PROJECT_RE.match(line)
        if project_match:
            current_project = project_match.group("project")
            continue
        task_match = _TASK_RE.match(line)
        if not task_match or not current_project:
            continue
        prefix = task_match.group("prefix")
        if prefix not in {" ", "*"}:
            continue
        shown = project_counts.get(current_project, 0)
        if shown >= per_project_limit:
            continue
        candidates.append(
            ReadyTaskCandidate(
                project_id=current_project,
                task_id=task_match.group("task_id"),
                priority=int(task_match.group("priority")),
                task_type=task_match.group("task_type"),
                mode=task_match.group("mode"),
                title=task_match.group("title").strip(),
            )
        )
        project_counts[current_project] = shown + 1

    return candidates


def build_actionable_ready_summary(
    task_overview: str,
    *,
    per_project_limit: int = 2,
) -> str:
    """Build a short explicit executable-task section from ready-all output."""
    candidates = extract_ready_task_candidates(task_overview, per_project_limit=per_project_limit)
    if not candidates:
        return ""
    lines = [f"ACTIONABLE-READY[{len(candidates)}]"]
    for candidate in candidates:
        lines.append(
            f"- {candidate.project_id} | {candidate.task_id} | "
            f"P{candidate.priority} {candidate.task_type} [{candidate.mode}] | {candidate.title}"
        )
    return "\n".join(lines)


def extract_project_overviews(task_overview: str) -> list[ProjectOverview]:
    """Extract compact per-project count labels from ready-all output."""
    overviews: list[ProjectOverview] = []
    for raw_line in task_overview.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        match = _PROJECT_RE.match(line)
        if not match:
            continue
        overviews.append(
            ProjectOverview(
                project_id=match.group("project"),
                label=match.group("label").strip(),
            )
        )
    return overviews


def build_compact_task_overview(
    task_overview: str,
    *,
    per_project_limit: int = 2,
) -> str:
    """Build a compact ready-all summary for prompt injection."""
    if not task_overview.strip():
        return ""

    lines: list[str] = []
    first_line = task_overview.strip().splitlines()[0]
    if first_line:
        lines.append(first_line)

    project_overviews = extract_project_overviews(task_overview)
    if project_overviews:
        lines.append("")
        lines.append(f"PROJECTS[{len(project_overviews)}]")
        for overview in project_overviews:
            lines.append(f"- {overview.project_id} | {overview.label}")

    actionable = build_actionable_ready_summary(task_overview, per_project_limit=per_project_limit)
    if actionable:
        lines.append("")
        lines.append(actionable)

    return "\n".join(lines)


__all__ = [
    "ReadyTaskCandidate",
    "TaskOverviewStats",
    "build_actionable_ready_summary",
    "build_compact_task_overview",
    "extract_project_overviews",
    "extract_ready_task_candidates",
    "parse_task_overview_stats",
]
