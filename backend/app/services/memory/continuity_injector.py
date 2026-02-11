"""
Cross-session continuity injection ("Recent Activity") for Agent Hub.

Generates a token-efficient markdown block summarizing recent session activity
from PostgreSQL session summaries. Includes context poisoning protection:
- Branch scoping: worktree summaries only visible to same branch + main
- Outcome filtering: abandoned sessions excluded, failed sessions prefixed
- Staleness check: only summaries < 48 hours old

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
from sqlalchemy import and_, or_, select

from app.db import _get_session_factory
from app.models import Session

logger = logging.getLogger(__name__)

# Staleness window: summaries older than this are excluded
STALENESS_HOURS = 48


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
        days: Maximum days to look back (default 7, capped by STALENESS_HOURS).

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
    """Query recent session summaries from PostgreSQL with poisoning protection.

    Applies branch scoping, outcome filtering, and staleness check.
    """
    staleness_cutoff = datetime.now(UTC) - timedelta(hours=STALENESS_HOURS)

    session_factory = _get_session_factory()
    async with session_factory() as db:
        # Base conditions: has summary, not abandoned, within staleness window
        conditions = [
            Session.summary_oneliner.isnot(None),
            or_(
                Session.summary_outcome != "abandoned",
                Session.summary_outcome.is_(None),
            ),
            Session.summary_generated_at > staleness_cutoff,
        ]

        # Project scoping
        if project_id:
            conditions.append(Session.project_id == project_id)

        # Branch scoping: show main/master to all, worktree summaries only to same branch
        if current_branch:
            conditions.append(
                or_(
                    Session.summary_branch.is_(None),
                    Session.summary_branch.in_(["main", "master", current_branch]),
                    # Non-worktree sessions are visible to all branches
                    Session.summary_is_worktree == False,  # noqa: E712
                )
            )

        query = (
            select(
                Session.id,
                Session.agent_slug,
                Session.summary_oneliner,
                Session.summary_outcome,
                Session.summary_branch,
                Session.summary_is_worktree,
                Session.created_at,
            )
            .where(and_(*conditions))
            .order_by(Session.created_at.desc())
            .limit(max_sessions)
        )

        result = await db.execute(query)
        rows = result.all()

    return [
        {
            "session_id": row.id,
            "agent_slug": row.agent_slug,
            "summary": row.summary_oneliner,
            "outcome": row.summary_outcome,
            "branch": row.summary_branch,
            "is_worktree": row.summary_is_worktree,
            "created_at": row.created_at,
        }
        for row in rows
    ]


def _format_recent_activity(summaries: list[dict[str, Any]]) -> str:
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
        delta = now - created
        if delta.total_seconds() < 3600:
            time_label = f"{int(delta.total_seconds() / 60)}m ago"
        elif delta.total_seconds() < 86400:
            time_label = f"{int(delta.total_seconds() / 3600)}h ago"
        elif delta.days == 1:
            time_label = "yesterday"
        else:
            time_label = f"{delta.days}d ago"

        # Agent annotation
        agent = s.get("agent_slug") or "session"

        # Outcome prefix for failed sessions
        summary_text = s["summary"]
        if s.get("outcome") == "failed":
            summary_text = f"FAILED: {summary_text}"

        lines.append(f"- [{time_label}] {agent}: {summary_text}")

    return "\n".join(lines)
