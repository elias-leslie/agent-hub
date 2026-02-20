"""Formatting utilities for continuity context markdown generation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def format_unified_timeline(
    summaries: list[dict[str, Any]] | None = None,
    cross_project: list[dict[str, Any]] | None = None,
    live_sessions: list[dict[str, Any]] | None = None,
    max_entries: int = 8,
) -> str:
    """Format all continuity entries into a single chronological timeline.

    Merges live sessions, recent activity (same project), and cross-project
    activity into one ``## Recent Activity`` section sorted by created_at DESC.

    Args:
        summaries: Recent activity entries for the current project.
        cross_project: Activity entries from other projects.
        live_sessions: Currently active sessions.
        max_entries: Maximum total entries to include (default 8).

    Returns:
        Markdown string with a single ``## Recent Activity`` header, or empty
        string if no entries survive filtering.
    """
    summaries = summaries or []
    cross_project = cross_project or []
    live_sessions = live_sessions or []

    # Normalize all entries into a common list of (created_at, formatted_line)
    entries: list[tuple[datetime, str]] = []

    now = datetime.now(UTC)

    # -- Live sessions --
    for s in live_sessions:
        created = _ensure_utc(s["created_at"])
        time_label = _format_time_label(now - created)
        agent = s.get("agent_slug") or "session"
        project = s.get("project_id", "unknown")

        external_id = s.get("external_id")
        last_touched = s.get("last_touched_file")

        if last_touched and external_id:
            detail = f"{external_id}, touching: {last_touched}"
        elif last_touched:
            detail = f"touching: {last_touched}"
        elif external_id:
            detail = f"{external_id}, {s.get('event_count', 0)} events"
        else:
            detail = f"{s.get('event_count', 0)} events"

        line = f"- [LIVE, {time_label}] {agent} on {project} ({detail})"
        entries.append((created, line))

    # -- Recent activity (same project) --
    for s in summaries:
        # Filter: exclude zero-learning failures (failed + no git_digest)
        if s.get("outcome") == "failed" and not s.get("git_digest"):
            continue

        created = _ensure_utc(s["created_at"])
        time_label = _format_time_label(now - created)
        agent = s.get("agent_slug") or "session"

        summary_text = s["summary"]
        if s.get("outcome") == "failed":
            summary_text = f"FAILED: {summary_text}"

        git_digest = s.get("git_digest")
        if git_digest:
            line = f"- [{time_label}] {agent}: {summary_text} | Changed: {git_digest}"
        else:
            line = f"- [{time_label}] {agent}: {summary_text}"

        entries.append((created, line))

    # -- Cross-project --
    for s in cross_project:
        # Filter: exclude zero-learning failures (failed + no git_digest)
        if s.get("outcome") == "failed" and not s.get("git_digest"):
            continue

        created = _ensure_utc(s["created_at"])
        time_label = _format_time_label(now - created)
        agent = s.get("agent_slug") or "session"
        project = s.get("project_id", "unknown")

        summary_text = s["summary"]
        if s.get("outcome") == "failed":
            summary_text = f"FAILED: {summary_text}"

        line = f"- [{time_label}] {project}/{agent}: {summary_text}"
        entries.append((created, line))

    if not entries:
        return ""

    # Sort by created_at DESC (newest first), then cap
    entries.sort(key=lambda e: e[0], reverse=True)
    entries = entries[:max_entries]

    lines = ["## Recent Activity"] + [line for _, line in entries]
    return "\n".join(lines)


# ── Backward-compatible thin wrappers ────────────────────────────────────


def format_recent_activity(summaries: list[dict[str, Any]]) -> str:
    """Format summaries into a Recent Activity block.

    Thin wrapper around :func:`format_unified_timeline` for backward
    compatibility.
    """
    return format_unified_timeline(summaries=summaries)


def format_cross_project_activity(summaries: list[dict[str, Any]]) -> str:
    """Format cross-project summaries.

    Thin wrapper around :func:`format_unified_timeline` for backward
    compatibility.
    """
    return format_unified_timeline(cross_project=summaries)


def format_live_sessions(sessions: list[dict[str, Any]]) -> str:
    """Format active sessions.

    Thin wrapper around :func:`format_unified_timeline` for backward
    compatibility.
    """
    return format_unified_timeline(live_sessions=sessions)


# ── Helpers ──────────────────────────────────────────────────────────────


def _ensure_utc(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware (UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


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
