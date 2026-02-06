"""
Cross-session continuity injection ("Previously on...") for Agent Hub.

Generates a markdown block summarizing recent session activity from previous
sessions, grouped by relative date. This helps new sessions understand what
work was done recently without re-reading entire session histories.

Usage:
    from app.services.memory.continuity_injector import build_continuity_context

    ctx = await build_continuity_context(project_id="my-project", days=7)
    if ctx.markdown:
        # Inject ctx.markdown into system prompt
        ...
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select

from app.db import _get_session_factory
from app.models import Session

logger = logging.getLogger(__name__)


class ContinuityContext(BaseModel):
    """Result of continuity context generation."""

    markdown: str
    session_count: int
    days_covered: int


async def build_continuity_context(
    project_id: str | None = None,
    days: int = 7,
    max_sessions: int = 10,
) -> ContinuityContext:
    """Build "Previously on..." context from recent session summaries.

    Queries recent completed/failed sessions from PostgreSQL, then searches
    Graphiti for their summary episodes, and formats the results into a
    markdown block grouped by relative date.

    Args:
        project_id: Filter to a specific project, or None for all projects.
        days: Number of days to look back (default 7).
        max_sessions: Maximum number of sessions to include (default 10).

    Returns:
        ContinuityContext with markdown block, session count, and days covered.
    """
    cutoff = datetime.now(UTC) - timedelta(days=days)

    # 1. Find recent completed/failed sessions from PostgreSQL
    sessions = await _get_recent_sessions(project_id, cutoff, max_sessions)
    if not sessions:
        return ContinuityContext(markdown="", session_count=0, days_covered=0)

    # 2. Search for summary episodes for these sessions in Graphiti
    summaries = await _get_session_summaries(sessions, project_id)

    # 3. Format into grouped markdown
    markdown = _format_continuity_markdown(summaries)

    return ContinuityContext(
        markdown=markdown,
        session_count=len(summaries),
        days_covered=days,
    )


async def _get_recent_sessions(
    project_id: str | None,
    cutoff: datetime,
    max_sessions: int,
) -> list[dict[str, Any]]:
    """Query recent completed/failed sessions from PostgreSQL."""
    session_factory = _get_session_factory()
    async with session_factory() as db:
        query = (
            select(
                Session.id,
                Session.project_id,
                Session.agent_slug,
                Session.session_type,
                Session.created_at,
                Session.updated_at,
            )
            .where(
                Session.status.in_(["completed", "failed"]),
                Session.created_at >= cutoff,
            )
            .order_by(Session.created_at.desc())
            .limit(max_sessions)
        )
        if project_id:
            query = query.where(Session.project_id == project_id)

        result = await db.execute(query)
        rows = result.all()

    return [
        {
            "session_id": row.id,
            "project_id": row.project_id,
            "agent_slug": row.agent_slug,
            "session_type": row.session_type,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        for row in rows
    ]


async def _get_session_summaries(
    sessions: list[dict[str, Any]],
    project_id: str | None,
) -> list[dict[str, Any]]:
    """Search Graphiti for session summary episodes matching these sessions.

    Session summaries are stored as episodes with content format:
        [Session Summary: {session_id}]
        {summary_text}

    We use text_search to find them by searching for "Session Summary: {sid}".
    """
    from app.services.memory.memory_models import MemoryScope
    from app.services.memory.service import get_memory_service

    # Use project scope if project_id is given, otherwise global
    if project_id:
        memory = get_memory_service(MemoryScope.PROJECT, project_id)
    else:
        memory = get_memory_service(MemoryScope.GLOBAL)

    summaries: list[dict[str, Any]] = []
    for session_info in sessions:
        sid = session_info["session_id"]
        try:
            episodes = await memory.text_search(
                query=f"Session Summary: {sid}",
                limit=1,
            )
            if episodes:
                ep = episodes[0]
                summaries.append(
                    {
                        "session_id": sid,
                        "project_id": session_info["project_id"],
                        "agent_slug": session_info["agent_slug"],
                        "session_type": session_info["session_type"],
                        "created_at": session_info["created_at"],
                        "content": ep.content,
                    }
                )
        except Exception as e:
            logger.debug("No summary found for session %s: %s", sid, e)
            continue

    return summaries


def _extract_summary_text(content: str) -> str:
    """Extract the summary text from an episode content block.

    Session summary episodes have the format:
        [Session Summary: {session_id}]
        {summary_text}

    This strips the header line and returns just the summary body.
    """
    if "\n" not in content:
        return content

    lines = content.split("\n")
    # Skip the [Session Summary: ...] header line
    if lines and lines[0].startswith("[Session Summary:"):
        body_lines = [line for line in lines[1:] if line.strip()]
        return "\n".join(body_lines).strip() if body_lines else content

    return content


def _format_continuity_markdown(summaries: list[dict[str, Any]]) -> str:
    """Format summaries into a date-grouped markdown block.

    Groups summaries by relative date (Today, Yesterday, N days ago, or
    calendar date for older entries) and formats them as a bullet list.
    """
    if not summaries:
        return ""

    now = datetime.now(UTC)
    groups: dict[str, list[str]] = {}

    for s in summaries:
        created = s["created_at"]
        if not hasattr(created, "date"):
            continue

        # Make created timezone-aware if it isn't already
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)

        delta = (now - created).days
        if delta == 0:
            label = "Today"
        elif delta == 1:
            label = "Yesterday"
        elif delta < 7:
            label = f"{delta} days ago"
        else:
            label = created.strftime("%b %d")

        summary_text = _extract_summary_text(s["content"])

        # Add agent and session type annotations
        annotations: list[str] = []
        if s.get("agent_slug"):
            annotations.append(s["agent_slug"])
        if s.get("session_type") and s["session_type"] != "completion":
            annotations.append(s["session_type"])

        suffix = f" ({', '.join(annotations)})" if annotations else ""
        entry = f"- {summary_text}{suffix}"

        if label not in groups:
            groups[label] = []
        groups[label].append(entry)

    if not groups:
        return ""

    parts = ["## Recent Activity"]
    for label, entries in groups.items():
        parts.append(f"### {label}")
        parts.extend(entries)

    return "\n".join(parts)
