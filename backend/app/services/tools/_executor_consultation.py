"""Consultation-related tool implementations for DirectToolExecutor.

Handles agent consultation, dispatch, steering, listing, and cancellation.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_CODING_TASK_KEYWORDS = (
    "code",
    "coding",
    "bug",
    "fix",
    "refactor",
    "implement",
    "test",
    "build",
    "lint",
    "compile",
    "typescript",
    "python",
    "sql",
    "frontend",
    "backend",
    "api",
    "file",
)


def _looks_like_coding_task(task: str) -> bool:
    """Heuristic to detect tasks likely requiring code modification."""
    task_lc = task.lower()
    return any(keyword in task_lc for keyword in _CODING_TASK_KEYWORDS)


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
        is_coding_agent = bool(resolved.agent.is_coding_agent)
        coding_task = _looks_like_coding_task(task)

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

        warning = ""
        if coding_task and not is_coding_agent:
            warning = (
                "Warning: task looks code-heavy but selected agent is marked non-coding. "
                "Proceeding as requested.\n"
            )

        return (
            f"{warning}Dispatched {agent_slug} "
            f"({'coding' if is_coding_agent else 'general'}). "
            f"Results will appear in your next heartbeat "
            f"context, or use query_sessions(agent_slug='{agent_slug}') to check status."
        )
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

    prompt = question
    if context:
        prompt = f"Context:\n{context}\n\nQuestion:\n{question}"

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
            messages: list[dict[str, str]] = []
            if mandate.system_content:
                messages.append({"role": "system", "content": mandate.system_content})
            messages.append({"role": "user", "content": prompt})

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
            content = result.content
            if session_id:
                return f"[session:{session_id}] {content}"
            return content
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
        from datetime import UTC, datetime, timedelta

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

        lines = []
        for s in sessions:
            created = s.created_at.strftime("%Y-%m-%d %H:%M") if s.created_at else "?"
            lines.append(
                f"- {s.agent_slug or '?'} | session={s.id} | "
                f"status={s.status} | created={created}"
            )

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
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import and_, select

        from app.db import async_session
        from app.models import Session as DBSession

        cutoff = datetime.now(UTC) - timedelta(hours=hours_back)
        conditions = [
            DBSession.created_at >= cutoff,
            DBSession.agent_slug.is_not(None),
        ]

        if agent_slug:
            conditions.append(DBSession.agent_slug == agent_slug)
        if status:
            conditions.append(DBSession.status == status)
        if parent_session_id:
            conditions.append(DBSession.parent_session_id == parent_session_id)

        async with async_session() as db:
            query = (
                select(DBSession)
                .where(and_(*conditions))
                .order_by(DBSession.created_at.desc())
                .limit(limit)
            )
            result = await db.execute(query)
            sessions = result.scalars().all()

        if not sessions:
            filters = []
            if agent_slug:
                filters.append(f"agent={agent_slug}")
            if status:
                filters.append(f"status={status}")
            if parent_session_id:
                filters.append(f"parent={parent_session_id}")
            filter_str = f" ({', '.join(filters)})" if filters else ""
            return f"(No sessions found in last {hours_back}h{filter_str})"

        now = datetime.now(UTC)
        lines = []
        for s in sessions:
            ago = int((now - s.created_at).total_seconds() / 60)
            time_label = f"{ago}m ago" if ago < 60 else f"{ago // 60}h ago"
            summary = ""
            if s.summary_oneliner:
                summary = f" — {s.summary_oneliner}"
            external_id = f" | task={s.external_id}" if s.external_id else ""
            lines.append(
                f"- {s.id} | {s.agent_slug or '?'} | {s.project_id} | "
                f"{s.provider}/{s.model}{external_id} | status={s.status} | {time_label}{summary}"
            )
        return "\n".join(lines)
    except Exception as e:
        logger.exception("query_sessions failed")
        return f"Error querying sessions: {e}"


async def cancel_consultation(session_id: str) -> str:
    """Close a running consultation session."""
    try:
        from sqlalchemy import select

        from app.db import async_session
        from app.models import Session as DBSession

        async with async_session() as db:
            result = await db.execute(
                select(DBSession).where(DBSession.id == session_id)
            )
            session = result.scalar_one_or_none()
            if not session:
                return f"Error: Session '{session_id}' not found."

            if session.request_source != "consultation":
                return f"Error: Session '{session_id}' is not a consultation."

            session.status = "completed"
            await db.commit()
            return f"Consultation session {session_id} closed."
    except Exception as e:
        logger.exception("cancel_consultation failed")
        return f"Error cancelling consultation: {e}"
