"""Helpers for summarizing `st cleanup status` output for agentic consumers."""

from __future__ import annotations

import re
from dataclasses import dataclass

_REPO_LINE_RE = re.compile(
    r"^(?P<project>[a-z0-9-]+) checkpoints:(?P<checkpoints>\d+) dirty:(?P<dirty>\d+) "
    r"orphan:(?P<orphan>\d+) prunable:(?P<prunable>\d+)(?P<rest>.*)$"
)
_TOKEN_RE = re.compile(
    r"(?P<kind>finalize|conflicts|review|salvage|review_orphans):"
    r"(?P<tasks>task-[a-z0-9]+(?:,task-[a-z0-9]+)*)"
)
_ORPHAN_BRANCH_RE = re.compile(
    r"orphan_branches:(?P<branches>task-[a-z0-9]+/main(?:,task-[a-z0-9]+/main)*)"
)
_RECONCILED_WORKSTREAM_STATUSES = {"authoritative", "superseded"}
_FILTERED_RECONCILED_ACTIONABLE_NOTE = (
    "ACTIONABLE-CLEANUP[0]\n"
    "- none (all task-backed cleanup residue is already reconciled authoritative/superseded)"
)


@dataclass(frozen=True)
class CleanupActionItem:
    """One actionable cleanup residue item surfaced from cleanup status."""

    project_id: str
    kind: str
    task_id: str


def extract_cleanup_action_items(cleanup_status: str) -> list[CleanupActionItem]:
    """Extract actionable cleanup tasks from cleanup status output."""
    items: list[CleanupActionItem] = []
    for raw_line in cleanup_status.splitlines():
        line = raw_line.strip()
        match = _REPO_LINE_RE.match(line)
        if not match:
            continue
        project_id = match.group("project")
        rest = match.group("rest")
        for token in _TOKEN_RE.finditer(rest):
            kind = token.group("kind")
            for task_id in token.group("tasks").split(","):
                items.append(CleanupActionItem(project_id=project_id, kind=kind, task_id=task_id))
        orphan_match = _ORPHAN_BRANCH_RE.search(rest)
        if orphan_match:
            for branch_name in orphan_match.group("branches").split(","):
                task_id = branch_name.split("/", 1)[0]
                items.append(CleanupActionItem(project_id=project_id, kind="orphan_branch", task_id=task_id))
    return items


def extract_cleanup_action_items_from_payload(cleanup_payload: dict[str, object]) -> list[CleanupActionItem]:
    """Extract actionable cleanup tasks from structured cleanup payloads."""
    items: list[CleanupActionItem] = []
    repositories = cleanup_payload.get("repositories")
    if not isinstance(repositories, list):
        return items

    task_fields = (
        ("needs_merge_tasks", "finalize"),
        ("conflict_tasks", "conflicts"),
        ("review_tasks", "review"),
        ("salvage_task_ids", "salvage"),
        ("review_orphan_task_ids", "review_orphans"),
    )

    for repo in repositories:
        if not isinstance(repo, dict):
            continue
        project_id = repo.get("project_id")
        if not isinstance(project_id, str) or not project_id:
            continue
        for field_name, kind in task_fields:
            task_ids = repo.get(field_name)
            if not isinstance(task_ids, list):
                continue
            for task_id in task_ids:
                if isinstance(task_id, str) and task_id:
                    items.append(CleanupActionItem(project_id=project_id, kind=kind, task_id=task_id))
        orphan_branch_names = repo.get("orphan_branch_names")
        if not isinstance(orphan_branch_names, list):
            continue
        for branch_name in orphan_branch_names:
            if not isinstance(branch_name, str) or not branch_name:
                continue
            task_id = branch_name.split("/", 1)[0]
            if task_id.startswith("task-"):
                items.append(
                    CleanupActionItem(project_id=project_id, kind="orphan_branch", task_id=task_id)
                )
    return items


def filter_reconciled_cleanup_items(
    items: list[CleanupActionItem],
    workstream_rows: list[dict[str, object]] | None,
) -> list[CleanupActionItem]:
    """Drop cleanup items for lanes already reconciled as authoritative/superseded."""
    if not items or not workstream_rows:
        return items

    from app.workflows._heartbeat_workstream import (
        _classify_workstream_lane,
        _group_rows_by_lane,
        _infer_lane_task_id,
    )

    reconciled_task_keys: set[tuple[str, str]] = set()
    for (project_id, _lane_key), lane_rows in _group_rows_by_lane(workstream_rows).items():
        if _classify_workstream_lane(lane_rows) != "reconciled":
            continue
        task_id = _infer_lane_task_id(lane_rows)
        if task_id:
            reconciled_task_keys.add((project_id, task_id))

    if reconciled_task_keys:
        return [
            item for item in items
            if (item.project_id, item.task_id) not in reconciled_task_keys
        ]

    statuses_by_task: dict[tuple[str, str], set[str]] = {}
    for row in workstream_rows:
        project_id = row.get("project_id")
        task_id = row.get("external_id")
        if not isinstance(project_id, str) or not isinstance(task_id, str):
            continue
        status = row.get("workstream_status")
        if not isinstance(status, str) or not status:
            continue
        statuses_by_task.setdefault((project_id, task_id), set()).add(status)

    for task_key, statuses in statuses_by_task.items():
        if _RECONCILED_WORKSTREAM_STATUSES.issubset(statuses):
            reconciled_task_keys.add(task_key)

    if not reconciled_task_keys:
        return items
    return [
        item for item in items
        if (item.project_id, item.task_id) not in reconciled_task_keys
    ]


def build_actionable_cleanup_summary(cleanup_status: str) -> str:
    """Build a short explicit actionable cleanup section from cleanup status output."""
    items = extract_cleanup_action_items(cleanup_status)
    return build_actionable_cleanup_summary_from_items(items)


def build_actionable_cleanup_summary_from_payload(cleanup_payload: dict[str, object]) -> str:
    """Build an actionable cleanup summary directly from structured payloads."""
    items = extract_cleanup_action_items_from_payload(cleanup_payload)
    return build_actionable_cleanup_summary_from_items(items)


def build_actionable_cleanup_summary_from_items(items: list[CleanupActionItem]) -> str:
    """Build a short explicit actionable cleanup section from extracted items."""
    if not items:
        return ""
    lines = [f"ACTIONABLE-CLEANUP[{len(items)}]"]
    for item in items:
        lines.append(f"- {item.project_id} | {item.kind} | {item.task_id}")
    return "\n".join(lines)


def build_filtered_reconciled_cleanup_note(
    raw_items: list[CleanupActionItem],
    filtered_items: list[CleanupActionItem],
) -> str:
    """Explain when cleanup residue exists in raw status but none remains actionable."""
    if raw_items and not filtered_items:
        return _FILTERED_RECONCILED_ACTIONABLE_NOTE
    return ""


__all__ = [
    "CleanupActionItem",
    "build_actionable_cleanup_summary",
    "build_actionable_cleanup_summary_from_items",
    "build_actionable_cleanup_summary_from_payload",
    "build_filtered_reconciled_cleanup_note",
    "extract_cleanup_action_items",
    "extract_cleanup_action_items_from_payload",
    "filter_reconciled_cleanup_items",
]
