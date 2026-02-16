"""
Cross-session continuity injection ("Recent Activity") for Agent Hub.

Generates a token-efficient markdown block summarizing recent session activity
from PostgreSQL session summaries. Includes context poisoning protection:
- Branch scoping: worktree summaries only visible to same branch + main
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
from app.services.memory.continuity_format import format_recent_activity
from app.services.memory.continuity_query import query_recent_summaries

logger = logging.getLogger(__name__)

# Staleness window: summaries older than this are excluded (7 days)
STALENESS_HOURS = 168


class ContinuityContext(BaseModel):
    """Result of continuity context generation."""

    markdown: str
    session_count: int
    days_covered: int


async def build_continuity_context(
    project_id: str | None = None,
    current_branch: str | None = None,
    max_sessions: int = 5,
    days: int = 7,
) -> ContinuityContext:
    """Build "Recent Activity" context from PostgreSQL session summaries.

    Queries session summary columns directly — no Graphiti involvement.
    Applies context poisoning protection:
    - Branch scoping: shows main summaries to all, worktree summaries only to same branch
    - Outcome filtering: excludes 'abandoned', prefixes 'failed' with FAILED:
    - Staleness: only includes summaries generated within STALENESS_HOURS

    Args:
        project_id: Filter to a specific project.
        current_branch: Current git branch for branch scoping.
        max_sessions: Maximum sessions to include.
        days: Maximum days to look back (default 7, matches STALENESS_HOURS).

    Returns:
        ContinuityContext with markdown block.
    """
    summaries = await _query_recent_summaries(
        project_id=project_id,
        current_branch=current_branch,
        max_sessions=max_sessions,
    )

    if not summaries:
        return ContinuityContext(markdown="", session_count=0, days_covered=0)

    markdown = _format_recent_activity(summaries)

    return ContinuityContext(
        markdown=markdown,
        session_count=len(summaries),
        days_covered=days,
    )


async def _query_recent_summaries(
    project_id: str | None,
    current_branch: str | None,
    max_sessions: int,
) -> list[dict[str, Any]]:
    """Query recent summaries from segments table, falling back to session columns.

    Primary path: query SessionSummarySegment rows (one per work period),
    joined with Session for metadata (agent_slug, project_id).

    Fallback: for pre-migration sessions that have summary columns but no
    segments, supplement with session-column data.

    Applies branch scoping, outcome filtering, and staleness check.
    """
    staleness_cutoff = datetime.now(UTC) - timedelta(hours=STALENESS_HOURS)

    session_factory = _get_session_factory()
    async with session_factory() as db:
        summaries = await query_recent_summaries(
            db,
            project_id,
            current_branch,
            max_sessions,
            staleness_cutoff,
        )

        return summaries


def _format_recent_activity(summaries: list[dict[str, Any]]) -> str:
    """Format summaries into a compact Recent Activity block.

    Target: ~100-200 tokens for 3-5 sessions.
    Format:
        ## Recent Activity
        - [2h ago] coder: Fixed auth bug in auth.py. Decided: use bcrypt over argon2.
        - [5h ago] refactor: Split completion.py into package. All 1097 tests pass.
        - [yesterday] coder: FAILED: Permission denied for writes in worktree context.
    """
    return format_recent_activity(summaries)
