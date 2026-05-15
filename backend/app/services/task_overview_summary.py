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
    ready_count: int = 0
    blocked_count: int = 0
    active_count: int = 0
    stale_count: int = 0
    completion_ready_count: int = 0
    blocked_completion_ready_count: int = 0
    queued_completion_ready_count: int = 0
    unknown_completion_ready_count: int = 0
    blocked_reasons: tuple[str, ...] = ()


def _task_completion_bucket(task: dict[str, object]) -> str | None:
    """Classify task completion readiness into a small summary bucket."""
    readiness = task.get("completion_readiness")
    if not isinstance(readiness, dict):
        return None
    ready = readiness.get("ready")
    reason = readiness.get("reason")
    if ready is True:
        return "ready"
    if isinstance(reason, str) and reason.strip().lower() == "unknown":
        return "unknown"
    return "blocked"


def _collect_completion_ready_stats(tasks: object) -> tuple[int, int, int, int]:
    """Return ready/blocked/queued/unknown completion counts from project tasks."""
    if not isinstance(tasks, list):
        return (0, 0, 0, 0)
    ready = blocked = queued = unknown = 0
    for task in tasks:
        if not isinstance(task, dict):
            continue
        bucket = _task_completion_bucket(task)
        if bucket == "ready":
            ready += 1
        elif bucket == "blocked":
            blocked += 1
        elif bucket == "unknown":
            unknown += 1
        else:
            queued += 1
    return ready, blocked, queued, unknown


def _collect_blocked_reasons(tasks: object) -> tuple[str, ...]:
    """Return distinct blocked completion reasons present in project tasks."""
    if not isinstance(tasks, list):
        return ()
    reasons: list[str] = []
    seen: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            continue
        readiness = task.get("completion_readiness")
        if not isinstance(readiness, dict) or readiness.get("ready") is True:
            continue
        reason = readiness.get("reason")
        if not isinstance(reason, str):
            continue
        normalized = reason.strip().lower()
        if not normalized or normalized == "unknown" or normalized in seen:
            continue
        seen.add(normalized)
        reasons.append(normalized)
    return tuple(reasons)


def _format_project_label(
    *,
    ready: int,
    blocked: int,
    active: int,
    stale: int,
    completion_ready: int,
    blocked_completion_ready: int,
    queued_completion_ready: int,
    unknown_completion_ready: int,
    blocked_reasons: tuple[str, ...],
) -> str:
    """Build compact per-project label with closure-state hints when present."""
    parts = [f"{ready} ready"]
    if blocked:
        parts.append(f"{blocked} blocked")
    if active:
        parts.append(f"{active} active")
    if stale:
        parts.append(f"{stale} stale")
    closure_parts: list[str] = []
    if completion_ready:
        closure_parts.append(f"{completion_ready} closure-ready")
    if blocked_completion_ready:
        closure_parts.append(f"{blocked_completion_ready} closure-blocked")
    if unknown_completion_ready:
        closure_parts.append(f"{unknown_completion_ready} closure-unknown")
    if queued_completion_ready:
        closure_parts.append(f"{queued_completion_ready} closure-queued")
    if closure_parts:
        parts.append("completion=" + "/".join(closure_parts))
    if blocked_reasons:
        parts.append("blocked-by=" + ",".join(blocked_reasons))
    return ", ".join(parts)


def _project_overview_from_payload(project: dict[str, object]) -> ProjectOverview | None:
    """Convert one project payload row into a compact overview with closure hints."""
    pid = project.get("project_id")
    if not isinstance(pid, str) or not pid:
        return None
    ready = _coerce_int(project.get("ready_count"))
    blocked = _coerce_int(project.get("blocked_count"))
    active = _coerce_int(project.get("active_count"))
    stale = _coerce_int(project.get("stale_count"))
    completion_ready, blocked_completion_ready, queued_completion_ready, unknown_completion_ready = (
        _collect_completion_ready_stats(project.get("ready_tasks"))
    )
    blocked_reasons = _collect_blocked_reasons(project.get("ready_tasks"))
    return ProjectOverview(
        project_id=pid,
        label=_format_project_label(
            ready=ready,
            blocked=blocked,
            active=active,
            stale=stale,
            completion_ready=completion_ready,
            blocked_completion_ready=blocked_completion_ready,
            queued_completion_ready=queued_completion_ready,
            unknown_completion_ready=unknown_completion_ready,
            blocked_reasons=blocked_reasons,
        ),
        ready_count=ready,
        blocked_count=blocked,
        active_count=active,
        stale_count=stale,
        completion_ready_count=completion_ready,
        blocked_completion_ready_count=blocked_completion_ready,
        queued_completion_ready_count=queued_completion_ready,
        unknown_completion_ready_count=unknown_completion_ready,
        blocked_reasons=blocked_reasons,
    )


def _format_completion_summary(project_overviews: list[ProjectOverview]) -> str:
    """Build cross-project closure summary for heartbeat/task consumers."""
    completion_ready = sum(overview.completion_ready_count for overview in project_overviews)
    blocked = sum(overview.blocked_completion_ready_count for overview in project_overviews)
    queued = sum(overview.queued_completion_ready_count for overview in project_overviews)
    unknown = sum(overview.unknown_completion_ready_count for overview in project_overviews)
    total = completion_ready + blocked + queued + unknown
    if total == 0:
        return ""
    reasons: list[str] = []
    seen: set[str] = set()
    for overview in project_overviews:
        for reason in overview.blocked_reasons:
            if reason in seen:
                continue
            seen.add(reason)
            reasons.append(reason)
    parts = [f"COMPLETION-READY[{completion_ready} ready"]
    if blocked:
        parts.append(f"{blocked} blocked")
    if unknown:
        parts.append(f"{unknown} unknown")
    if queued:
        parts.append(f"{queued} queued")
    summary = ", ".join(parts) + "]"
    if reasons:
        summary += f"\nCOMPLETION-BLOCKERS[{','.join(reasons)}]"
    return summary


def _parse_completion_summary(task_overview: str) -> str:
    """Extract existing completion summary block from compact ready-all text."""
    lines = [line.rstrip() for line in task_overview.splitlines()]
    collected: list[str] = []
    capture = False
    for line in lines:
        if line.startswith("COMPLETION-READY["):
            collected = [line]
            capture = True
            continue
        if capture and line.startswith("COMPLETION-BLOCKERS["):
            collected.append(line)
            continue
        if capture:
            break
    return "\n".join(collected)


def extract_completion_summary_from_payload(
    task_overview_payload: dict[str, object],
    *,
    project_id: str | None = None,
) -> str:
    """Build cross-project completion summary directly from ready-all payloads."""
    return _format_completion_summary(
        extract_project_overviews_from_payload(task_overview_payload, project_id=project_id)
    )


def extract_completion_summary(task_overview: str) -> str:
    """Extract completion summary block from compact ready-all text when present."""
    return _parse_completion_summary(task_overview)


def completion_ready_visible(task_overview_payload: dict[str, object], *, project_id: str | None = None) -> bool:
    """Return True when at least one visible task is completion-ready."""
    for overview in extract_project_overviews_from_payload(task_overview_payload, project_id=project_id):
        if overview.completion_ready_count > 0:
            return True
    return False


def has_unknown_completion_blocker(task_overview_payload: dict[str, object], *, project_id: str | None = None) -> bool:
    """Return True when visible tasks carry unknown completion-readiness state."""
    for overview in extract_project_overviews_from_payload(task_overview_payload, project_id=project_id):
        if overview.unknown_completion_ready_count > 0:
            return True
    return False


def has_dirty_completion_blocker(task_overview_payload: dict[str, object], *, project_id: str | None = None) -> bool:
    """Return True when visible tasks are blocked by dirty-worktree closure reasons."""
    target = "uncommitted changes"
    for overview in extract_project_overviews_from_payload(task_overview_payload, project_id=project_id):
        if any(target in reason for reason in overview.blocked_reasons):
            return True
    return False


def summarize_completion_blockers(task_overview_payload: dict[str, object], *, project_id: str | None = None) -> tuple[str, ...]:
    """Return distinct completion blockers from visible ready tasks."""
    reasons: list[str] = []
    seen: set[str] = set()
    for overview in extract_project_overviews_from_payload(task_overview_payload, project_id=project_id):
        for reason in overview.blocked_reasons:
            if reason in seen:
                continue
            seen.add(reason)
            reasons.append(reason)
    return tuple(reasons)


def should_suppress_step_999_auto_defect(task_overview_payload: dict[str, object], *, project_id: str | None = None) -> bool:
    """Return True when closure plumbing already explains the failure better than step 999."""
    return has_unknown_completion_blocker(task_overview_payload, project_id=project_id)


def should_allow_completion_reconcile_despite_dirty_worktree(
    task_overview_payload: dict[str, object],
    *,
    project_id: str | None = None,
) -> bool:
    """Return True when at least one visible task is completion-ready despite dirty-tree blockers elsewhere."""
    for overview in extract_project_overviews_from_payload(task_overview_payload, project_id=project_id):
        if overview.completion_ready_count > 0:
            return True
    return False


def _coerce_int(value: object, default: int = 0) -> int:
    """Return value as int when possible, else default."""
    return value if isinstance(value, int) else default


def _candidate_from_payload_task(
    project_id: str,
    task: dict[str, object],
) -> ReadyTaskCandidate | None:
    """Convert one task payload row into the compact heartbeat candidate shape."""
    task_id = task.get("id")
    if not isinstance(task_id, str) or not task_id:
        return None

    task_type = task.get("task_type")
    title = task.get("title")
    return ReadyTaskCandidate(
        project_id=project_id,
        task_id=task_id,
        priority=_coerce_int(task.get("priority"), default=3),
        task_type=task_type if isinstance(task_type, str) and task_type else "task",
        mode="A" if task.get("execution_mode") == "autonomous" else "M",
        title=title.strip() if isinstance(title, str) else "",
    )


def _extract_payload_task_candidates(
    task_overview_payload: dict[str, object],
    field_name: str,
    *,
    per_project_limit: int | None = 2,
    project_id: str | None = None,
) -> list[ReadyTaskCandidate]:
    """Extract heartbeat task candidates directly from ready-all API payloads."""
    raw_projects = task_overview_payload.get("projects")
    if not isinstance(raw_projects, list):
        return []
    candidates: list[ReadyTaskCandidate] = []
    for project in raw_projects:
        if not isinstance(project, dict):
            continue
        if project_id is not None and project.get("project_id") != project_id:
            continue
        pid = project.get("project_id")
        if not isinstance(pid, str) or not pid:
            continue
        tasks = project.get(field_name)
        if not isinstance(tasks, list):
            continue
        shown = 0
        for task in tasks:
            if not isinstance(task, dict):
                continue
            candidate = _candidate_from_payload_task(pid, task)
            if candidate is None:
                continue
            candidates.append(candidate)
            shown += 1
            if per_project_limit is not None and shown >= per_project_limit:
                break
    return candidates


def _extract_task_candidates(
    task_overview: str,
    *,
    allowed_prefixes: set[str],
    per_project_limit: int = 2,
    required_suffix: str | None = None,
) -> list[ReadyTaskCandidate]:
    """Extract task candidates matching prefixes/suffixes from ready-all output."""
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
        suffix = (task_match.group("suffix") or "").strip()
        if prefix not in allowed_prefixes:
            continue
        if required_suffix is not None and suffix != required_suffix:
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


def _format_actionable_summary(header: str, candidates: list[ReadyTaskCandidate]) -> str:
    """Format a labelled actionable section from a list of candidates."""
    if not candidates:
        return ""
    lines = [f"{header}[{len(candidates)}]"]
    for c in candidates:
        lines.append(
            f"- {c.project_id} | {c.task_id} | "
            f"P{c.priority} {c.task_type} [{c.mode}] | {c.title}"
        )
    return "\n".join(lines)


def parse_task_overview_stats_from_payload(task_overview_payload: dict[str, object]) -> TaskOverviewStats:
    """Parse ready-all headline counts from structured API payloads."""
    summary = task_overview_payload.get("summary")
    if not isinstance(summary, dict):
        return TaskOverviewStats()
    return TaskOverviewStats(
        ready=_coerce_int(summary.get("ready")),
        blocked=_coerce_int(summary.get("blocked")),
        active=_coerce_int(summary.get("active")),
        stale=_coerce_int(summary.get("stale")),
        projects=_coerce_int(summary.get("projects")),
    )


def extract_project_overviews_from_payload(
    task_overview_payload: dict[str, object],
    *,
    project_id: str | None = None,
) -> list[ProjectOverview]:
    """Extract compact per-project overview rows from ready-all API payloads."""
    raw_projects = task_overview_payload.get("projects")
    if not isinstance(raw_projects, list):
        return []
    overviews: list[ProjectOverview] = []
    for project in raw_projects:
        if not isinstance(project, dict):
            continue
        if project_id is not None and project.get("project_id") != project_id:
            continue
        overview = _project_overview_from_payload(project)
        if overview is not None:
            overviews.append(overview)
    return overviews


def build_actionable_ready_summary_from_payload(
    task_overview_payload: dict[str, object],
    *,
    per_project_limit: int = 2,
    project_id: str | None = None,
) -> str:
    """Build actionable ready-task summary directly from ready-all API payloads."""
    candidates = _extract_payload_task_candidates(
        task_overview_payload,
        "ready_tasks",
        per_project_limit=per_project_limit,
        project_id=project_id,
    )
    return _format_actionable_summary("ACTIONABLE-READY", candidates)


def build_actionable_blocked_summary_from_payload(
    task_overview_payload: dict[str, object],
    *,
    per_project_limit: int = 2,
    project_id: str | None = None,
) -> str:
    """Build actionable blocked-task summary directly from ready-all API payloads."""
    candidates = _extract_payload_task_candidates(
        task_overview_payload,
        "blocked_tasks",
        per_project_limit=per_project_limit,
        project_id=project_id,
    )
    return _format_actionable_summary("ACTIONABLE-BLOCKED", candidates)


def extract_stale_task_candidates_from_payload(
    task_overview_payload: dict[str, object],
    *,
    per_project_limit: int | None = None,
    project_id: str | None = None,
) -> list[ReadyTaskCandidate]:
    """Extract stale-running task rows directly from ready-all API payloads."""
    return _extract_payload_task_candidates(
        task_overview_payload,
        "stale_tasks",
        per_project_limit=per_project_limit,
        project_id=project_id,
    )


def build_actionable_stale_summary_from_payload(
    task_overview_payload: dict[str, object],
    *,
    per_project_limit: int = 2,
    project_id: str | None = None,
) -> str:
    """Build actionable stale-running summary directly from ready-all API payloads."""
    candidates = extract_stale_task_candidates_from_payload(
        task_overview_payload,
        per_project_limit=per_project_limit,
        project_id=project_id,
    )
    return _format_actionable_summary("ACTIONABLE-STALE", candidates)


def collect_visible_task_ids_from_payload(
    task_overview_payload: dict[str, object],
    *,
    project_id: str | None = None,
) -> set[str]:
    """Collect visible queue task ids from a ready-all API payload."""
    task_ids: set[str] = set()
    for field_name in ("ready_tasks", "blocked_tasks", "active_tasks", "stale_tasks"):
        for candidate in _extract_payload_task_candidates(
            task_overview_payload,
            field_name,
            per_project_limit=None,
            project_id=project_id,
        ):
            task_ids.add(candidate.task_id)
    return task_ids


def build_compact_task_overview_from_payload(
    task_overview_payload: dict[str, object],
    *,
    per_project_limit: int = 2,
    project_id: str | None = None,
) -> str:
    """Build the heartbeat-ready compact overview directly from API payloads."""
    stats = parse_task_overview_stats_from_payload(task_overview_payload)
    project_overviews = extract_project_overviews_from_payload(
        task_overview_payload,
        project_id=project_id,
    )
    if not project_overviews and stats.projects == 0:
        return ""

    lines = [
        (
            f"READY-ALL[{stats.ready} ready, {stats.blocked} blocked, "
            f"{stats.active} active, {stats.stale} stale across {stats.projects} projects]"
        )
    ]

    if project_overviews:
        lines.append("")
        lines.append(f"PROJECTS[{len(project_overviews)}]")
        for overview in project_overviews:
            lines.append(f"- {overview.project_id} | {overview.label}")

    completion_summary = _format_completion_summary(project_overviews)
    if completion_summary:
        lines.extend(["", completion_summary])

    for section in [
        build_actionable_ready_summary_from_payload(
            task_overview_payload, per_project_limit=per_project_limit, project_id=project_id,
        ),
        build_actionable_blocked_summary_from_payload(
            task_overview_payload, per_project_limit=per_project_limit, project_id=project_id,
        ),
        build_actionable_stale_summary_from_payload(
            task_overview_payload, per_project_limit=per_project_limit, project_id=project_id,
        ),
    ]:
        if section:
            lines.extend(["", section])

    return "\n".join(lines)


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
    return _extract_task_candidates(
        task_overview,
        allowed_prefixes={" ", "*"},
        per_project_limit=per_project_limit,
    )


def build_actionable_ready_summary(
    task_overview: str,
    *,
    per_project_limit: int = 2,
) -> str:
    """Build a short explicit executable-task section from ready-all output."""
    candidates = extract_ready_task_candidates(task_overview, per_project_limit=per_project_limit)
    return _format_actionable_summary("ACTIONABLE-READY", candidates)


def build_actionable_blocked_summary(
    task_overview: str,
    *,
    per_project_limit: int = 2,
) -> str:
    """Build a short explicit blocked-task section from ready-all output."""
    candidates = _extract_task_candidates(
        task_overview,
        allowed_prefixes={"!"},
        per_project_limit=per_project_limit,
    )
    return _format_actionable_summary("ACTIONABLE-BLOCKED", candidates)


def build_actionable_stale_summary(
    task_overview: str,
    *,
    per_project_limit: int = 2,
) -> str:
    """Build a short explicit stale-running section from ready-all output."""
    candidates = _extract_task_candidates(
        task_overview,
        allowed_prefixes={"?"},
        per_project_limit=per_project_limit,
        required_suffix="stale-running",
    )
    return _format_actionable_summary("ACTIONABLE-STALE", candidates)


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

    completion_summary = _parse_completion_summary(task_overview)
    if completion_summary:
        lines.extend(["", completion_summary])

    for section in [
        build_actionable_ready_summary(task_overview, per_project_limit=per_project_limit),
        build_actionable_blocked_summary(task_overview, per_project_limit=per_project_limit),
        build_actionable_stale_summary(task_overview, per_project_limit=per_project_limit),
    ]:
        if section:
            lines.extend(["", section])

    return "\n".join(lines)


__all__ = [
    "ReadyTaskCandidate",
    "TaskOverviewStats",
    "build_actionable_blocked_summary",
    "build_actionable_blocked_summary_from_payload",
    "build_actionable_ready_summary",
    "build_actionable_ready_summary_from_payload",
    "build_actionable_stale_summary",
    "build_actionable_stale_summary_from_payload",
    "build_compact_task_overview",
    "build_compact_task_overview_from_payload",
    "collect_visible_task_ids_from_payload",
    "extract_completion_summary",
    "extract_completion_summary_from_payload",
    "extract_project_overviews",
    "extract_project_overviews_from_payload",
    "extract_ready_task_candidates",
    "extract_stale_task_candidates_from_payload",
    "has_dirty_completion_blocker",
    "has_unknown_completion_blocker",
    "parse_task_overview_stats",
    "parse_task_overview_stats_from_payload",
    "should_allow_completion_reconcile_despite_dirty_worktree",
    "should_suppress_step_999_auto_defect",
    "summarize_completion_blockers",
]
