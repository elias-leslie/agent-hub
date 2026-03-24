"""Helpers for summarizing `st cleanup status` output for agentic consumers."""

from __future__ import annotations

import re
from dataclasses import dataclass

_REPO_LINE_RE = re.compile(
    r"^(?P<project>[a-z0-9-]+) worktrees:(?P<worktrees>\d+) dirty:(?P<dirty>\d+) "
    r"orphan:(?P<orphan>\d+) prunable:(?P<prunable>\d+)(?P<rest>.*)$"
)
_TOKEN_RE = re.compile(
    r"(?P<kind>finalize|conflicts|review|salvage|review_orphans):"
    r"(?P<tasks>task-[a-z0-9]+(?:,task-[a-z0-9]+)*)"
)
_ORPHAN_BRANCH_RE = re.compile(
    r"orphan_branches:(?P<branches>task-[a-z0-9]+/main(?:,task-[a-z0-9]+/main)*)"
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


__all__ = [
    "CleanupActionItem",
    "build_actionable_cleanup_summary",
    "build_actionable_cleanup_summary_from_items",
    "build_actionable_cleanup_summary_from_payload",
    "extract_cleanup_action_items",
    "extract_cleanup_action_items_from_payload",
]
