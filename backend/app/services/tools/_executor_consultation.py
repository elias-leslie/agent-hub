"""Consultation-related tool implementations for DirectToolExecutor.

Handles agent consultation, dispatch, steering, listing, and cancellation.
Specialist dispatch logic lives in _executor_dispatch.py.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from app.constants.models import FAST_CLAUDE_MODEL

from ._executor_dispatch import (
    _SPECIALIST_AGENT_SLUGS,
    SpecialistDispatchPlan,
    dispatch_result_text,
    parse_specialist_dispatch_request,
    prepare_specialist_dispatch,
)

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
    from app.services.tools._standard_tools import STANDARD_TOOLS
    from app.services.tools.tool_definitions import get_agent_tool_specs

    tool_specs = get_agent_tool_specs(agent_slug) if agent_slug else None
    source_tools = tool_specs or STANDARD_TOOLS
    allowed_names = _consultation_allowed_tool_names()
    return [_tool_spec_to_api_tool(tool) for tool in source_tools if tool.name in allowed_names]


async def _consultation_max_turns(db: Any) -> int:
    from app.services._persona_crud import get_persona_limit
    from app.services.persona_service import get_persona

    persona = await get_persona(db)
    return get_persona_limit(persona, "max_turns")


def _consultation_permission_config(tools: list[dict[str, Any]]) -> dict[str, Any]:
    from app.services.tools.permissions import PermissionConfig

    return PermissionConfig.granular(
        allow=[str(tool["name"]) for tool in tools],
    ).to_dict()


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


async def dispatch_agent(
    project_id: str | None,
    agent_slug: str,
    task: str,
    max_turns: int | None = None,
    parent_session_id: str | None = None,
) -> str:
    """Dispatch an agent via Hatchet wake workflow (fire-and-forget)."""
    if not project_id:
        return "Error: project_id not configured, cannot dispatch agent"
    try:
        from app.db import async_session
        from app.services.agent_routing_utils import resolve_agent
        from app.workflows.persona_wake import dispatch_wake

        async with async_session() as db:
            resolved = await resolve_agent(agent_slug, db)
            dispatch_request = parse_specialist_dispatch_request(task)
            dispatch_plan = (
                await prepare_specialist_dispatch(
                    db=db, project_id=project_id, agent_slug=agent_slug, task=task,
                )
                if dispatch_request.mode is not None or agent_slug in _SPECIALIST_AGENT_SLUGS
                else SpecialistDispatchPlan(event_type="dispatch")
            )

        wake_kwargs: dict[str, Any] = {
            "agent_slug": agent_slug,
            "model": resolved.model,
            "provider": resolved.provider,
            "temperature": resolved.agent.temperature,
            "prompt": task,
            "project_id": project_id,
            "event_type": dispatch_plan.event_type,
            "thinking_level": resolved.agent.thinking_level,
            "max_turns": max_turns,
            "parent_session_id": parent_session_id,
            "current_branch": dispatch_plan.current_branch,
            "working_dir": dispatch_plan.working_dir,
        }
        if dispatch_plan.event_type == "dispatch_task" and dispatch_request.task_id:
            wake_kwargs["task_id"] = dispatch_request.task_id

        dispatch_wake(
            **wake_kwargs,
        )
        return dispatch_result_text(agent_slug, bool(resolved.agent.is_coding_agent), task)
    except ValueError as e:
        return str(e)
    except Exception as e:
        logger.exception(f"dispatch_agent failed for '{agent_slug}'")
        return f"Error dispatching agent '{agent_slug}': {e}"


async def consult_agent(
    project_id: str | None,
    agent_slug: str,
    question: str,
    context: str = "",
) -> str:
    """Consult another agent for advice with read-only research tools."""
    if not project_id:
        return "Error: project_id not configured, cannot consult agent"

    prompt = f"Context:\n{context}\n\nQuestion:\n{question}" if context else question

    try:
        from app.api.complete.core import complete_internal
        from app.db import async_session
        from app.services.agent_routing_utils import inject_agent_mandates, resolve_agent

        async with async_session() as db:
            resolved = await resolve_agent(agent_slug, db)
            mandate = await inject_agent_mandates(
                resolved.agent, db, prompt_mode="minimal", project_id=project_id,
            )
            consultation_tools = _consultation_tools(agent_slug)
            consultation_max_turns = await _consultation_max_turns(db)
            messages = _build_consultation_messages(mandate.system_content, prompt)
            result = await complete_internal(
                messages=messages, model=resolved.model, provider=resolved.provider,
                temperature=resolved.agent.temperature, project_id=project_id,
                db=db, agent_slug=agent_slug, request_source="consultation",
                use_memory=True, memory_group_id=f"project-{project_id}",
                max_turns=consultation_max_turns,
                execute_tools=bool(consultation_tools),
                tools=consultation_tools,
                permission_config=_consultation_permission_config(consultation_tools),
            )
        session_id = result.session_id if hasattr(result, "session_id") else None
        return f"[session:{session_id}] {result.content}" if session_id else result.content
    except Exception as e:
        logger.exception(f"consult_agent failed for '{agent_slug}'")
        return f"Error consulting agent '{agent_slug}': {e}"


async def steer_consultation(project_id: str | None, session_id: str, message: str) -> str:
    """Send a follow-up message to an existing consultation session."""
    if not project_id:
        return "Error: project_id not configured"
    try:
        from app.api.complete.core import complete_internal
        from app.db import async_session

        async with async_session() as db:
            consultation_tools = _consultation_tools()
            consultation_max_turns = await _consultation_max_turns(db)
            result = await complete_internal(
                messages=[{"role": "user", "content": message}],
                model=FAST_CLAUDE_MODEL, provider="claude", temperature=0.3,
                project_id=project_id, db=db, session_id=session_id,
                request_source="consultation",
                max_turns=consultation_max_turns,
                execute_tools=bool(consultation_tools),
                tools=consultation_tools,
                permission_config=_consultation_permission_config(consultation_tools),
            )
            return f"[session:{session_id}] {result.content}"
    except Exception as e:
        logger.exception("steer_consultation failed")
        return f"Error steering consultation: {e}"


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
            sessions = [session for session in sessions if is_session_actionably_active(session)]
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


def _format_inspect_output(session: DBSession, events: list[DBSessionEvent]) -> str:
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
