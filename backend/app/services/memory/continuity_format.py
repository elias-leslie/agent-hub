"""Formatting utilities for continuity context markdown generation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def format_recent_activity(summaries: list[dict[str, Any]]) -> str:
    """Format summaries into a compact Recent Activity block.

    Target: ~100-200 tokens for 3-5 sessions.
    Format:
        ## Recent Activity
        - [2h ago] coder: Fixed auth bug in auth.py. Decided: use bcrypt over argon2.
        - [5h ago] refactor: Split completion.py into package. All 1097 tests pass.
        - [yesterday] coder: FAILED: Permission denied for writes in worktree context.
    """
    if not summaries:
        return ""

    now = datetime.now(UTC)
    lines: list[str] = ["## Recent Activity"]

    for s in summaries:
        created = s["created_at"]
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)

        # Relative time label
        time_label = _format_time_label(now - created)

        # Agent annotation
        agent = s.get("agent_slug") or "session"

        # Outcome prefix for failed sessions
        summary_text = s["summary"]
        if s.get("outcome") == "failed":
            summary_text = f"FAILED: {summary_text}"

        # Append git digest when available for richer context
        git_digest = s.get("git_digest")
        if git_digest:
            summary_text += f" | Changed: {git_digest}"

        lines.append(f"- [{time_label}] {agent}: {summary_text}")

    return "\n".join(lines)


def _format_time_label(delta: Any) -> str:
    """Convert timedelta to human-readable label (e.g., '2h ago', 'yesterday')."""
    total_seconds = delta.total_seconds()

    if total_seconds < 3600:
        return f"{int(total_seconds / 60)}m ago"

    if total_seconds < 86400:
        return f"{int(total_seconds / 3600)}h ago"

    if delta.days == 1:
        return "yesterday"

    return f"{delta.days}d ago"
