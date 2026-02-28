"""Summary tag processing helpers for session_analysis."""

from __future__ import annotations


def build_git_digest(git_context: str | None) -> str:
    """Build a short digest string from raw git log output."""
    if not git_context:
        return ""
    commit_lines = [ln.strip() for ln in git_context.strip().split("\n") if ln.strip()]
    if not commit_lines:
        return ""
    subjects = [
        cl.split(" ", 1)[1] if " " in cl else cl
        for cl in commit_lines[:3]
    ]
    return "; ".join(subjects)[:500]
