"""Consultation-related tool implementations for DirectToolExecutor.

Handles agent consultation, dispatch, steering, listing, and cancellation.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models import Session as DBSession

logger = logging.getLogger(__name__)

_CODING_TASK_KEYWORDS = (
    "code", "coding", "bug", "fix", "refactor", "implement", "test",
    "build", "lint", "compile", "typescript", "python", "sql",
    "frontend", "backend", "api", "file",
)


def _session_working_dir(session: object) -> str | None:
    metadata = getattr(session, "provider_metadata", None)
    if not isinstance(metadata, dict):
        return None
    cwd = metadata.get("cwd")
    return cwd if isinstance(cwd, str) and cwd else None


def _provider_model_label(provider: str, model: str) -> str:
    """Format provider/model without duplicating already-prefixed model ids."""
    prefix = f"{provider}/"
    return model if model.startswith(prefix) else f"{provider}/{model}"


def _terminal_result_line(session: DBSession) -> str | None:
    """Return a terminal-state line derived from live activity metadata when available."""
    try:
        from app.services.session_live_activity import build_live_activity_response

        activity = build_live_activity_response(session)
    except Exception:
        logger.debug("Failed to build terminal live activity for inspect_session", exc_info=True)
        return None

    if not activity:
        return None

    status = str(activity.get("status") or session.status)
    summary = activity.get("summary")
    termination_reason = activity.get("termination_reason")
    if status not in {"completed", "failed", "error"} and not termination_reason:
        return None

    parts = [f"Latest result: {status}"]
    if isinstance(summary, str) and summary:
        parts.append(summary)
    if isinstance(termination_reason, str) and termination_reason:
        parts.append(f"reason={termination_reason}")
    return " | ".join(parts)


def _looks_like_coding_task(task: str) -> bool:
    """Heuristic to detect tasks likely requiring code modification."""
    return any(keyword in task.lower() for keyword in _CODING_TASK_KEYWORDS)


def _dispatch_result_text(agent_slug: str, is_coding_agent: bool, task: str) -> str:
    warning = (
        "Warning: task looks code-heavy but selected agent is marked non-coding. "
        "Proceeding as requested.\n"
        if _looks_like_coding_task(task) and not is_coding_agent
        else ""
    )
    kind = "coding" if is_coding_agent else "general"
    return (
        f"{warning}Dispatched {agent_slug} ({kind}). "
        f"Results will appear in your next heartbeat context, "
        f"or use query_sessions(agent_slug='{agent_slug}') to check status."
    )


def _build_consultation_messages(
    system_content: str | None, prompt: str
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if system_content:
        messages.append({"role": "system", "content": system_content})
    messages.append({"role": "user", "content": prompt})
    return messages


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


def _format_session_line(s: DBSession, now: datetime) -> str:
    ago = int((now - s.created_at).total_seconds() / 60)
    time_label = f"{ago}m ago" if ago < 60 else f"{ago // 60}h ago"
    summary = f" — {s.summary_oneliner}" if s.summary_oneliner else ""
    lane_parts = [
        *([f"task={s.external_id}"] if s.external_id else []),
        *([f"branch={s.current_branch}"] if getattr(s, "current_branch", None) else []),
        *([f"lane={s.workstream_status}"] if getattr(s, "workstream_status", None) else []),
        *([f"cwd={cwd}"] if (cwd := _session_working_dir(s)) else []),
    ]
    lane_suffix = f" | {' | '.join(lane_parts)}" if lane_parts else ""
    activity_suffix = ""
    try:
        from app.services.session_live_activity import build_live_activity_response

        activity = build_live_activity_response(s)
    except Exception:
        logger.debug("Failed to build live activity response for query_sessions", exc_info=True)
        activity = None

    if activity:
        activity_parts = [
            f"health={activity.get('health') or 'unknown'}",
            f"phase={activity.get('phase') or 'unknown'}",
        ]
        quiet_for_seconds = activity.get("quiet_for_seconds")
        if quiet_for_seconds is not None:
            activity_parts.append(f"quiet={quiet_for_seconds}s")
        if activity.get("current_tool_name"):
            activity_parts.append(f"tool={activity['current_tool_name']}")
        elif activity.get("last_event_type"):
            activity_parts.append(f"last={activity['last_event_type']}")
        if activity.get("stalled") and activity.get("stall_reason"):
            activity_parts.append(f"stall={activity['stall_reason']}")
        activity_suffix = f" | {' | '.join(activity_parts)}"
    return (
        f"- {s.id} | {s.agent_slug or '?'} | {s.project_id} | "
        f"{_provider_model_label(s.provider, s.model)}{lane_suffix} | "
        f"status={s.status}{activity_suffix} | {time_label}{summary}"
    )


async def dispatch_agent(
    project_id: str | None,
    agent_slug: str,
    task: str,
    max_turns: int = 25,
    parent_session_id: str | None = None,
) -> str:
    """Dispatch an agent via Hatchet wake workflow (fire-and-forget).

    Resolves agent config (fast DB lookup), then enqueues a Hatchet wake task
    that runs complete_internal() asynchronously. Returns immediately so the
    MCP handler doesn't block and the IPC connection stays alive.
    """
    if not project_id:
        return "Error: project_id not configured, cannot dispatch agent"

    try:
        from app.db import async_session
        from app.services.agent_routing_utils import resolve_agent
        from app.workflows.persona_wake import dispatch_wake

        async with async_session() as db:
            resolved = await resolve_agent(agent_slug, db)

        dispatch_wake(
            agent_slug=agent_slug,
            model=resolved.model,
            provider=resolved.provider,
            temperature=resolved.agent.temperature,
            prompt=task,
            project_id=project_id,
            event_type="dispatch",
            thinking_level=resolved.agent.thinking_level,
            max_turns=max_turns,
            parent_session_id=parent_session_id,
        )
        return _dispatch_result_text(agent_slug, bool(resolved.agent.is_coding_agent), task)
    except Exception as e:
        logger.exception(f"dispatch_agent failed for '{agent_slug}'")
        return f"Error dispatching agent '{agent_slug}': {e}"


async def consult_agent(
    project_id: str | None,
    agent_slug: str,
    question: str,
    context: str = "",
) -> str:
    """Consult another agent for advice without executing tools."""
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
                resolved.agent, db, prompt_mode="minimal",
                project_id=project_id,
            )
            messages = _build_consultation_messages(mandate.system_content, prompt)
            result = await complete_internal(
                messages=messages,
                model=resolved.model,
                provider=resolved.provider,
                temperature=resolved.agent.temperature,
                project_id=project_id,
                db=db,
                agent_slug=agent_slug,
                request_source="consultation",
                use_memory=True,
                memory_group_id=f"project-{project_id}",
                max_turns=1,
                execute_tools=False,
            )
        session_id = result.session_id if hasattr(result, "session_id") else None
        return f"[session:{session_id}] {result.content}" if session_id else result.content
    except Exception as e:
        logger.exception(f"consult_agent failed for '{agent_slug}'")
        return f"Error consulting agent '{agent_slug}': {e}"


async def steer_consultation(
    project_id: str | None,
    session_id: str,
    message: str,
) -> str:
    """Send a follow-up message to an existing consultation session."""
    if not project_id:
        return "Error: project_id not configured"

    try:
        from app.api.complete.core import complete_internal
        from app.db import async_session

        async with async_session() as db:
            result = await complete_internal(
                messages=[{"role": "user", "content": message}],
                model="claude-haiku-4-5",
                provider="claude",
                temperature=0.3,
                project_id=project_id,
                db=db,
                session_id=session_id,
                request_source="consultation",
                max_turns=1,
                execute_tools=False,
            )
            return f"[session:{session_id}] {result.content}"
    except Exception as e:
        logger.exception("steer_consultation failed")
        return f"Error steering consultation: {e}"


async def list_consultations(
    hours_back: int = 24,
    agent_slug: str | None = None,
) -> str:
    """List recent consultation sessions."""
    try:
        from sqlalchemy import select

        from app.db import async_session
        from app.models import Session as DBSession

        cutoff = datetime.now(UTC) - timedelta(hours=hours_back)

        async with async_session() as db:
            query = (
                select(DBSession)
                .where(
                    DBSession.request_source == "consultation",
                    DBSession.created_at >= cutoff,
                )
                .order_by(DBSession.created_at.desc())
                .limit(50)
            )
            if agent_slug:
                query = query.where(DBSession.agent_slug == agent_slug)
            result = await db.execute(query)
            sessions = result.scalars().all()

        if not sessions:
            return f"(No consultations in the last {hours_back} hours)"

        lines = [
            f"- {s.agent_slug or '?'} | session={s.id} | "
            f"status={s.status} | created={s.created_at.strftime('%Y-%m-%d %H:%M') if s.created_at else '?'}"
            for s in sessions
        ]
        return "\n".join(lines)
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
    """Query agent sessions for observability — check progress, find stuck agents."""
    try:
        from sqlalchemy import and_, select

        from app.db import async_session
        from app.models import Session as DBSession

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
                select(DBSession)
                .where(and_(*conditions))
                .order_by(DBSession.created_at.desc())
                .limit(limit)
            )
            sessions = result.scalars().all()

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
            session_result = await db.execute(
                select(DBSession).where(DBSession.id == session_id)
            )
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

        latest_assistant = next(
            (e for e in events if e.event_type == "assistant_message" and e.content),
            None,
        )
        latest_error = next(
            (e for e in events if e.event_type == "error" and e.content),
            None,
        )
        recent_tools = [
            e.tool_name for e in events
            if e.event_type == "tool_use" and e.tool_name
        ][:5]

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
            result = await db.execute(
                select(DBSession).where(DBSession.id == session_id)
            )
            session = result.scalar_one_or_none()
            if not session:
                return f"Error: Session '{session_id}' not found."
            if session.request_source != "consultation":
                return f"Error: Session '{session_id}' is not a consultation."
            mark_session_completed(
                session,
                summary="Consultation cancelled",
                termination_reason="consultation_cancelled",
            )
            await db.commit()
            return f"Consultation session {session_id} closed."
    except Exception as e:
        logger.exception("cancel_consultation failed")
        return f"Error cancelling consultation: {e}"
