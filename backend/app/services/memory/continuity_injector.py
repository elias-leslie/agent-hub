"""
Cross-session continuity injection ("Recent Activity") for Agent Hub.

Generates a token-efficient markdown block summarizing recent session activity
from PostgreSQL session summaries. Includes context poisoning protection:
- Branch scoping: summaries only visible to same branch + main
- Outcome filtering: abandoned sessions excluded, failed sessions prefixed
- Staleness check: only summaries < 7 days old

Usage:
    from app.services.memory.continuity_injector import build_continuity_context

    ctx = await build_continuity_context(
        project_id="my-project",
        current_branch="main",
        max_sessions=5,
    )
    if ctx.markdown:
        # Inject ctx.markdown into system prompt
        ...
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel

from app.db import _get_session_factory
from app.services.memory.continuity_format import format_unified_timeline
from app.services.memory.continuity_query import (
    query_active_sessions,
    query_cross_project_summaries,
    query_recent_summaries,
)

logger = logging.getLogger(__name__)

# Staleness window: summaries older than this are excluded (7 days)
STALENESS_HOURS = 168


class ContinuityContext(BaseModel):
    """Result of continuity context generation."""

    markdown: str
    session_count: int
    days_covered: int


async def _query_continuity_data(
    project_id: str | None,
    current_branch: str | None,
    max_sessions: int,
    staleness_cutoff: datetime,
    include_cross_project: bool,
    include_live_sessions: bool,
    exclude_session_id: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Query all continuity data from the database.

    Returns:
        Tuple of (summaries, cross_project_summaries, live_sessions).
    """
    session_factory = _get_session_factory()
    async with session_factory() as db:
        summaries = await query_recent_summaries(
            db,
            project_id,
            current_branch,
            max_sessions,
            staleness_cutoff,
        )

        cross_project_summaries: list[dict[str, Any]] = []
        if include_cross_project and project_id:
            cross_project_summaries = await query_cross_project_summaries(
                db,
                exclude_project_id=project_id,
                max_entries=2,
                staleness_cutoff=staleness_cutoff,
            )

        live_sessions: list[dict[str, Any]] = []
        if include_live_sessions:
            live_sessions = await query_active_sessions(
                db,
                project_id=None,
                exclude_session_id=exclude_session_id,
                max_entries=5,
            )

    return summaries, cross_project_summaries, live_sessions


def _build_markdown_sections(
    summaries: list[dict[str, Any]],
    cross_project_summaries: list[dict[str, Any]],
    live_sessions: list[dict[str, Any]],
) -> list[str]:
    """Build markdown sections from queried continuity data.

    Returns:
        List of markdown section strings (may be empty).
    """
    unified = format_unified_timeline(
        summaries=summaries,
        cross_project=cross_project_summaries,
        live_sessions=live_sessions,
    )
    if unified:
        return [unified]
    return []


async def build_continuity_context(
    project_id: str | None = None,
    current_branch: str | None = None,
    max_sessions: int = 5,
    days: int = 7,
    include_cross_project: bool = True,
    include_live_sessions: bool = True,
    exclude_session_id: str | None = None,
) -> ContinuityContext:
    """Build "Recent Activity" context from PostgreSQL session summaries.

    Queries session summary columns directly from PostgreSQL.
    Applies branch scoping, outcome filtering, and staleness protection.
    Optionally includes live sessions and cross-project summaries.

    Args:
        project_id: Filter to a specific project.
        current_branch: Current git branch for branch scoping.
        max_sessions: Maximum sessions to include.
        days: Maximum days to look back (default 7, matches STALENESS_HOURS).
        include_cross_project: Show summaries from other projects (default True).
        include_live_sessions: Show currently active sessions (default True).
        exclude_session_id: Exclude this session from live sessions list.

    Returns:
        ContinuityContext with markdown block.
    """
    staleness_cutoff = datetime.now(UTC) - timedelta(hours=STALENESS_HOURS)

    summaries, cross_project_summaries, live_sessions = await _query_continuity_data(
        project_id=project_id,
        current_branch=current_branch,
        max_sessions=max_sessions,
        staleness_cutoff=staleness_cutoff,
        include_cross_project=include_cross_project,
        include_live_sessions=include_live_sessions,
        exclude_session_id=exclude_session_id,
    )

    sections = _build_markdown_sections(summaries, cross_project_summaries, live_sessions)

    if not sections:
        return ContinuityContext(markdown="", session_count=0, days_covered=0)

    return ContinuityContext(
        markdown="\n\n".join(sections),
        session_count=len(summaries),
        days_covered=days,
    )
