"""Helpers for summarizing `st git status` output for heartbeat decisions."""

from __future__ import annotations

import re
from dataclasses import dataclass

_HEADLINE_RE = re.compile(r"^GIT\[(?P<count>\d+)\]$")
_REPO_LINE_RE = re.compile(
    r"^(?P<project>\S+)\s+"
    r"(?P<branch>\S+)\s+"
    r"(?P<state>clean|dirty|behind|ahead)\s+"
    r"uncommitted:(?P<uncommitted>\d+)\s+"
    r"ahead:(?P<ahead>\d+)\s+"
    r"behind:(?P<behind>\d+)$"
)


@dataclass(frozen=True)
class RepoGitStatus:
    """One repository row parsed from `st git status` compact output."""

    project_id: str
    branch: str
    state: str
    uncommitted: int
    ahead: int
    behind: int


def parse_git_status_rows(git_status: str) -> list[RepoGitStatus]:
    """Parse compact `st git status` output into structured rows."""
    rows: list[RepoGitStatus] = []
    for raw_line in git_status.splitlines():
        line = raw_line.strip()
        if not line or _HEADLINE_RE.match(line):
            continue
        match = _REPO_LINE_RE.match(line)
        if not match:
            continue
        rows.append(
            RepoGitStatus(
                project_id=match.group("project"),
                branch=match.group("branch"),
                state=match.group("state"),
                uncommitted=int(match.group("uncommitted")),
                ahead=int(match.group("ahead")),
                behind=int(match.group("behind")),
            )
        )
    return rows


def build_compact_git_status(rows: list[RepoGitStatus]) -> str:
    """Render compact git status text from structured repository rows."""
    if not rows:
        return ""
    lines = [f"GIT[{len(rows)}]"]
    for row in rows:
        lines.append(
            f"{row.project_id:<15} {row.branch:<15} {row.state:<7} "
            f"uncommitted:{row.uncommitted} ahead:{row.ahead} behind:{row.behind}"
        )
    return "\n".join(lines)


def _next_action(row: RepoGitStatus) -> str:
    """Return the default next action for one repo row."""
    if row.behind > 0 and row.uncommitted == 0:
        return "sync_before_new_work"
    if row.uncommitted > 0 and row.ahead > 0:
        return "inspect_then_publish"
    if row.uncommitted > 0:
        return "inspect_then_commit_or_dispatch"
    if row.ahead > 0:
        return "publish_pending_commits"
    return "no_action"


def build_actionable_git_summary(git_status: str) -> str:
    """Build an explicit actionable summary from compact `st git status` output."""
    rows = parse_git_status_rows(git_status)
    return build_actionable_git_summary_from_rows(rows)


def build_actionable_git_summary_from_rows(rows: list[RepoGitStatus]) -> str:
    """Build an explicit actionable summary from structured repository rows."""
    actionable = [
        row
        for row in rows
        if row.uncommitted > 0 or row.ahead > 0 or row.behind > 0
    ]
    if not actionable:
        return ""

    lines = [f"ACTIONABLE-GIT[{len(actionable)}]"]
    for row in actionable:
        lines.append(
            f"- {row.project_id} | branch={row.branch} | state={row.state} | "
            f"uncommitted={row.uncommitted} | ahead={row.ahead} | behind={row.behind} | "
            f"next={_next_action(row)}"
        )
    return "\n".join(lines)


__all__ = [
    "RepoGitStatus",
    "build_actionable_git_summary",
    "build_actionable_git_summary_from_rows",
    "build_compact_git_status",
    "parse_git_status_rows",
]
