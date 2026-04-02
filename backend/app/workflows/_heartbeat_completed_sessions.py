"""Heartbeat completed-sessions helpers.

Helpers for querying and rendering recently completed sessions
for heartbeat display.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.services.session_display_summary import SessionDisplaySummaryCandidate
from app.workflows._heartbeat_state import _BENCHMARK_EXTERNAL_ID_PREFIXES

# Time window constants
_COMPLETED_SESSION_LOOKBACK_HOURS = 2
_COMPLETED_SESSION_LIMIT = 10

# Session classification constants
_SESSION_STATUS_COMPLETED = "completed"
_PERSONA_AGENT_SLUG = "persona"


async def _query_completed_sessions_with_summaries(
    target_project_id: str | None,
    *,
    now: datetime,
) -> tuple[list[object], object]:
    """Query completed sessions and their display summaries from DB."""
    from sqlalchemy import and_, select

    from app.db import async_session
    from app.models import Session
    from app.workflows._heartbeat_data import fetch_session_display_summary_results

    cutoff = now - timedelta(hours=_COMPLETED_SESSION_LOOKBACK_HOURS)
    async with async_session() as db:
        result = await db.execute(
            select(
                Session.id, Session.agent_slug, Session.project_id,
                Session.external_id, Session.summary_oneliner, Session.created_at,
            )
            .where(and_(
                Session.status == _SESSION_STATUS_COMPLETED,
                Session.created_at >= cutoff,
                Session.summary_oneliner.isnot(None),
                Session.agent_slug != _PERSONA_AGENT_SLUG,
                Session.project_id == target_project_id if target_project_id else True,
            ))
            .order_by(Session.created_at.desc())
            .limit(_COMPLETED_SESSION_LIMIT)
        )
        rows = list(result.all())
        display_summaries = await fetch_session_display_summary_results(
            db,
            [
                SessionDisplaySummaryCandidate(
                    session_id=row.id,
                    summary_oneliner=row.summary_oneliner,
                )
                for row in rows
            ],
        )
    return rows, display_summaries  # type: ignore[return-value]


def _is_valid_summary_result(summary_result: object) -> bool:
    """Return True if a summary result is valid for heartbeat display."""
    if not summary_result:
        return False
    return bool(
        getattr(summary_result, "summary", None)
        and getattr(summary_result, "has_summary_tag", False)
        and getattr(summary_result, "summary_outcome", None) == _SESSION_STATUS_COMPLETED
        and not getattr(summary_result, "has_unresolved_blocker", False)
    )


def _render_completed_session_rows(
    rows: list[object],
    display_summaries: dict[object, object],
    now: datetime,
) -> list[tuple[object, str]]:
    """Filter and render completed session rows for heartbeat display."""
    rendered_rows: list[tuple[object, str]] = []
    for row in rows:
        external_id = str(getattr(row, "external_id", "") or "")
        if external_id.startswith(_BENCHMARK_EXTERNAL_ID_PREFIXES):
            continue
        ago = int((now - getattr(row, "created_at", now)).total_seconds() / 60)
        time_label = f"{ago}m ago" if ago < 60 else f"{ago // 60}h ago"
        summary_result = display_summaries.get(getattr(row, "id", None))
        if not _is_valid_summary_result(summary_result):
            continue
        rendered_rows.append((
            row,
            f"- {getattr(row, 'agent_slug', None) or '?'} on {getattr(row, 'project_id', '?')}: "
            f"{summary_result.summary} ({time_label})",  # type: ignore[union-attr]
        ))
    return rendered_rows
