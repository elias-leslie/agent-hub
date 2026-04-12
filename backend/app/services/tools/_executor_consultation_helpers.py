"""Private helpers for _executor_consultation.py.

Formatting, session-inspection utilities, and tool-config builders extracted
to keep the main consultation module under 200 lines.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models import Session as DBSession
    from app.models import SessionEvent as DBSessionEvent
    from app.services.tools.base import Tool

logger = logging.getLogger(__name__)

_CONSULTATION_TOOL_BLOCKLIST = frozenset({
    "bash",
    "write_file",
    "consult_agent",
    "dispatch_agent",
    "steer_consultation",
    "cancel_consultation",
    "schedule_job",
    "cancel_scheduled_job",
    "send_push",
    "manage_tasks",
    "manage_backups",
})


# ---------------------------------------------------------------------------
# Session metadata helpers
# ---------------------------------------------------------------------------

def _session_working_dir(session: object) -> str | None:
    metadata = getattr(session, "provider_metadata", None)
    if not isinstance(metadata, dict):
        return None
    cwd = metadata.get("cwd")
    return cwd if isinstance(cwd, str) and cwd else None


def _provider_model_label(provider: str, model: str) -> str:
    prefix = f"{provider}/"
    return model if model.startswith(prefix) else f"{provider}/{model}"


def _terminal_result_line(session: DBSession) -> str | None:
    try:
        from app.services.session_live_activity import build_live_activity_response
        activity = build_live_activity_response(session)
    except Exception:
        logger.debug("Failed to build terminal live activity for inspect_session", exc_info=True)
        return None

    if not activity:
        return None

    status = str(activity.get("status") or session.status)
    termination_reason = activity.get("termination_reason")
    if status not in {"completed", "failed", "error"} and not termination_reason:
        return None

    parts = [f"Latest result: {status}"]
    summary = activity.get("summary")
    if isinstance(summary, str) and summary:
        parts.append(summary)
    if isinstance(termination_reason, str) and termination_reason:
        parts.append(f"reason={termination_reason}")
    return " | ".join(parts)


# ---------------------------------------------------------------------------
# Consultation tool/config builders
# ---------------------------------------------------------------------------

def _build_consultation_messages(system_content: str | None, prompt: str) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if system_content:
        messages.append({"role": "system", "content": system_content})
    messages.append({"role": "user", "content": prompt})
    return messages


def _consultation_allowed_tool_names() -> frozenset[str]:
    from app.services.project_permission_service import get_tools_for_tier

    return get_tools_for_tier("read") - _CONSULTATION_TOOL_BLOCKLIST


def _tool_spec_to_api_tool(tool: Tool) -> dict[str, Any]:
    api_tool: dict[str, Any] = {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.input_schema,
    }
    if tool.allowed_callers != ["direct"]:
        api_tool["allowed_callers"] = list(tool.allowed_callers)
    return api_tool


def _consultation_tools(agent_slug: str | None = None) -> list[dict[str, Any]]:
    from app.services.tools._standard_tools import (
        FETCH_WEB_PAGE_TOOL,
        PRECISION_CODE_SEARCH_TOOL,
        READ_FILE_TOOL,
        RESEARCH_WEB_TOOL,
        SEARCH_WEB_TOOL,
    )
    from app.services.tools.tool_definitions import get_agent_tool_specs

    tool_specs = get_agent_tool_specs(agent_slug) if agent_slug else None
    source_tools = tool_specs or [
        READ_FILE_TOOL,
        PRECISION_CODE_SEARCH_TOOL,
        RESEARCH_WEB_TOOL,
        SEARCH_WEB_TOOL,
        FETCH_WEB_PAGE_TOOL,
    ]
    allowed_names = _consultation_allowed_tool_names()
    return [_tool_spec_to_api_tool(tool) for tool in source_tools if tool.name in allowed_names]


async def _consultation_max_turns(db: Any) -> int:
    from app.services._persona_crud import get_persona_limit
    from app.services.persona_service import get_persona

    persona = await get_persona(db)
    return get_persona_limit(persona, "max_turns")


async def parent_dispatch_limit_block(db: Any, parent_session_id: str | None) -> str | None:
    """Return a blocking message when the parent session already hit its child-session cap."""
    if not parent_session_id:
        return None

    from sqlalchemy import select

    from app.models import Session as DBSession
    from app.services.agent_routing_utils import resolve_agent
    from app.services.ownership_inventory import (
        query_project_active_specialists,
        query_project_ownership,
    )
    from app.services.session_live_activity import is_session_actionably_active

    parent = (
        await db.execute(select(DBSession).where(DBSession.id == parent_session_id).limit(1))
    ).scalar_one_or_none()
    parent_agent_slug = getattr(parent, "agent_slug", None)
    if not isinstance(parent_agent_slug, str) or not parent_agent_slug:
        return None

    resolved_parent = await resolve_agent(parent_agent_slug, db)
    limit = getattr(resolved_parent.agent, "max_subagent_concurrency", None)
    if not isinstance(limit, int) or limit < 1:
        return None

    child_sessions = (
        await db.execute(
            select(DBSession)
            .where(
                DBSession.status == "active",
                DBSession.parent_session_id == parent_session_id,
            )
            .order_by(DBSession.created_at.desc())
        )
    ).scalars().all()
    if not child_sessions:
        return None

    owner_session_ids: set[str] = set()
    specialist_session_ids: set[str] = set()
    for project_id in sorted({session.project_id for session in child_sessions if session.project_id}):
        owner_session_ids.update(
            str(session_id)
            for owner in await query_project_ownership(db, project_id)
            if (session_id := getattr(owner, "session_id", None))
        )
        specialist_session_ids.update(
            str(session_id)
            for specialist in await query_project_active_specialists(db, project_id)
            if (session_id := getattr(specialist, "session_id", None))
        )

    active_children = [
        session
        for session in child_sessions
        if is_session_actionably_active(
            session,
            has_owner_lane=session.id in owner_session_ids,
            has_specialist_lane=session.id in specialist_session_ids,
        )
    ]
    if len(active_children) < limit:
        return None

    return (
        f"Dispatch blocked for {parent_agent_slug}: parent session already has "
        f"{len(active_children)} active child session(s); "
        f"max_subagent_concurrency={limit}."
    )


# ---------------------------------------------------------------------------
# Session list / format helpers
# ---------------------------------------------------------------------------

def _empty_sessions_msg(
    hours_back: int,
    agent_slug: str | None,
    status: str | None,
    parent_session_id: str | None,
) -> str:
    parts = [
        *([f"agent={agent_slug}"] if agent_slug else []),
        *([f"status={status}"] if status else []),
        *([f"parent={parent_session_id}"] if parent_session_id else []),
    ]
    filter_str = f" ({', '.join(parts)})" if parts else ""
    return f"(No sessions found in last {hours_back}h{filter_str})"


def _format_lane_suffix(s: DBSession) -> str:
    lane_parts = [
        *([f"task={s.external_id}"] if s.external_id else []),
        *([f"branch={s.current_branch}"] if getattr(s, "current_branch", None) else []),
        *([f"lane={s.workstream_status}"] if getattr(s, "workstream_status", None) else []),
        *([f"cwd={cwd}"] if (cwd := _session_working_dir(s)) else []),
    ]
    return f" | {' | '.join(lane_parts)}" if lane_parts else ""


def _format_activity_suffix(s: DBSession) -> str:
    try:
        from app.services.session_live_activity import build_live_activity_response
        activity = build_live_activity_response(s)
    except Exception:
        logger.debug("Failed to build live activity response for query_sessions", exc_info=True)
        activity = None

    if not activity:
        return ""

    parts = [
        f"health={activity.get('health') or 'unknown'}",
        f"phase={activity.get('phase') or 'unknown'}",
    ]
    quiet_for_seconds = activity.get("quiet_for_seconds")
    if quiet_for_seconds is not None:
        parts.append(f"quiet={quiet_for_seconds}s")
    topic = activity.get("current_topic") or activity.get("last_topic")
    if isinstance(topic, str) and topic:
        parts.append(f"topic={topic}")
    if activity.get("current_tool_name"):
        parts.append(f"tool={activity['current_tool_name']}")
    elif activity.get("last_event_type"):
        parts.append(f"last={activity['last_event_type']}")
    if activity.get("stalled") and activity.get("stall_reason"):
        parts.append(f"stall={activity['stall_reason']}")
    return f" | {' | '.join(parts)}"


def _format_session_line(s: DBSession, now: datetime) -> str:
    ago = int((now - s.created_at).total_seconds() / 60)
    time_label = f"{ago}m ago" if ago < 60 else f"{ago // 60}h ago"
    summary = f" — {s.summary_oneliner}" if s.summary_oneliner else ""
    return (
        f"- {s.id} | {s.agent_slug or '?'} | {s.project_id} | "
        f"{_provider_model_label(s.provider, s.model)}{_format_lane_suffix(s)} | "
        f"status={s.status}{_format_activity_suffix(s)} | {time_label}{summary}"
    )


# ---------------------------------------------------------------------------
# inspect_session output formatter
# ---------------------------------------------------------------------------

def _format_inspect_output(session: DBSession, events: list[DBSessionEvent]) -> str:
    from app.services.session_live_activity import build_live_activity_response

    latest_assistant = next(
        (e for e in events if e.event_type == "assistant_message" and e.content), None,
    )
    latest_error = next(
        (e for e in events if e.event_type == "error" and e.content), None,
    )
    recent_tools = [e.tool_name for e in events if e.event_type == "tool_use" and e.tool_name][:5]

    lines = [
        f"Session: {session.id}",
        f"Agent: {session.agent_slug or '?'}",
        f"Project: {session.project_id}",
        f"Status: {session.status}",
    ]
    activity = build_live_activity_response(session)
    if activity:
        topic = activity.get("current_topic") or activity.get("last_topic")
        if isinstance(topic, str) and topic:
            lines.append(f"Topic: {topic}")
    if session.summary_oneliner:
        lines.append(f"Summary: {session.summary_oneliner}")
    if recent_tools:
        lines.append(f"Recent tools: {', '.join(recent_tools)}")
    terminal_line = _terminal_result_line(session)
    if latest_assistant and latest_assistant.content:
        lines.extend(["Latest assistant message:", latest_assistant.content.strip()])
    elif latest_error and latest_error.content:
        lines.extend(["Latest error:", latest_error.content.strip()])
    elif terminal_line:
        lines.append(terminal_line)
    else:
        lines.append("Latest result: (no assistant message stored yet)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Observability / management async functions
# ---------------------------------------------------------------------------

async def list_consultations(hours_back: int = 24, agent_slug: str | None = None) -> str:
    """List recent consultation sessions."""
    try:
        from sqlalchemy import select

        from app.db import async_session
        from app.models import Session as DBSession

        cutoff = datetime.now(UTC) - timedelta(hours=hours_back)
        async with async_session() as db:
            query = (
                select(DBSession)
                .where(DBSession.request_source == "consultation", DBSession.created_at >= cutoff)
                .order_by(DBSession.created_at.desc())
                .limit(50)
            )
            if agent_slug:
                query = query.where(DBSession.agent_slug == agent_slug)
            result = await db.execute(query)
            sessions = result.scalars().all()

        if not sessions:
            return f"(No consultations in the last {hours_back} hours)"
        return "\n".join(
            f"- {s.agent_slug or '?'} | session={s.id} | "
            f"status={s.status} | created={s.created_at.strftime('%Y-%m-%d %H:%M') if s.created_at else '?'}"
            for s in sessions
        )
    except Exception as e:
        logger.exception("list_consultations failed")
        return f"Error listing consultations: {e}"


async def query_sessions(
    agent_slug: str | None = None,
    status: str | None = None,
    hours_back: int = 24,
    limit: int = 10,
    parent_session_id: str | None = None,
) -> str:
    """Query agent sessions for observability."""
    try:
        from sqlalchemy import and_, select

        from app.db import async_session
        from app.models import Session as DBSession
        from app.services.session_live_activity import is_session_actionably_active

        cutoff = datetime.now(UTC) - timedelta(hours=hours_back)
        conditions = [DBSession.created_at >= cutoff, DBSession.agent_slug.is_not(None)]
        if agent_slug:
            conditions.append(DBSession.agent_slug == agent_slug)
        if status:
            conditions.append(DBSession.status == status)
        if parent_session_id:
            conditions.append(DBSession.parent_session_id == parent_session_id)

        async with async_session() as db:
            result = await db.execute(
                select(DBSession).where(and_(*conditions))
                .order_by(DBSession.created_at.desc()).limit(max(limit * 5, 25))
            )
            sessions = result.scalars().all()

        if status == "active":
            sessions = [s for s in sessions if is_session_actionably_active(s)]
        sessions = sessions[:limit]
        if not sessions:
            return _empty_sessions_msg(hours_back, agent_slug, status, parent_session_id)
        now = datetime.now(UTC)
        return "\n".join(_format_session_line(s, now) for s in sessions)
    except Exception as e:
        logger.exception("query_sessions failed")
        return f"Error querying sessions: {e}"


async def inspect_session(session_id: str) -> str:
    """Inspect a specific session and return a concise result-oriented summary."""
    try:
        from sqlalchemy import select

        from app.db import async_session
        from app.models import Session as DBSession
        from app.models import SessionEvent as DBSessionEvent

        async with async_session() as db:
            session_result = await db.execute(select(DBSession).where(DBSession.id == session_id))
            session = session_result.scalar_one_or_none()
            if session is None:
                return f"Error: session '{session_id}' not found"

            events_result = await db.execute(
                select(DBSessionEvent)
                .where(DBSessionEvent.session_id == session_id)
                .order_by(DBSessionEvent.turn.desc(), DBSessionEvent.sequence.desc())
                .limit(50)
            )
            events = list(events_result.scalars().all())

        return _format_inspect_output(session, events)
    except Exception as e:
        logger.exception("inspect_session failed")
        return f"Error inspecting session: {e}"


async def cancel_consultation(session_id: str) -> str:
    """Close a running consultation session."""
    try:
        from sqlalchemy import select

        from app.db import async_session
        from app.models import Session as DBSession
        from app.services.session_live_activity import mark_session_completed

        async with async_session() as db:
            result = await db.execute(select(DBSession).where(DBSession.id == session_id))
            session = result.scalar_one_or_none()
            if not session:
                return f"Error: Session '{session_id}' not found."
            if session.request_source != "consultation":
                return f"Error: Session '{session_id}' is not a consultation."
            mark_session_completed(
                session, summary="Consultation cancelled",
                termination_reason="consultation_cancelled",
            )
            await db.commit()
            return f"Consultation session {session_id} closed."
    except Exception as e:
        logger.exception("cancel_consultation failed")
        return f"Error cancelling consultation: {e}"
