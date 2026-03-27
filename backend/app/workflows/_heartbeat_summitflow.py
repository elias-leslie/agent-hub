"""SummitFlow API parsing helpers for heartbeat assembly.

The main IO functions (_fetch_summitflow_json, _fetch_*_response) live in
_heartbeat_data to keep test patch paths valid. This module provides the
pure parsing helpers that do not require patching.
"""

from __future__ import annotations

from app.services.git_status_summary import RepoGitStatus


def _parse_git_status_rows(repositories: list[object]) -> list[RepoGitStatus]:
    """Parse a list of repository dicts into typed RepoGitStatus objects."""
    rows: list[RepoGitStatus] = []
    for repo in repositories:
        if not isinstance(repo, dict):
            continue
        project_id = repo.get("project_id") or repo.get("name")
        branch = repo.get("branch")
        state = repo.get("state")
        uncommitted = repo.get("uncommitted")
        ahead = repo.get("ahead")
        behind = repo.get("behind")
        if (
            not isinstance(project_id, str)
            or not isinstance(branch, str)
            or not isinstance(state, str)
        ):
            continue
        if not all(isinstance(value, int) for value in (uncommitted, ahead, behind)):
            continue
        rows.append(
            RepoGitStatus(
                project_id=project_id,
                branch=branch,
                state=state,
                uncommitted=uncommitted,
                ahead=ahead,
                behind=behind,
            )
        )
    return rows
