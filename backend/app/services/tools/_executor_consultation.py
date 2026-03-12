"""Consultation-related tool implementations for DirectToolExecutor.

Handles agent consultation, dispatch, steering, listing, and cancellation.
"""

from __future__ import annotations

import logging
import re
import shlex
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models import Session as DBSession

logger = logging.getLogger(__name__)

_CODING_TASK_KEYWORDS = (
    "code", "coding", "bug", "fix", "refactor", "implement", "test",
    "build", "lint", "compile", "typescript", "python", "sql",
    "frontend", "backend", "api", "file",
)
_SPECIALIST_AGENT_SLUGS = frozenset({"refactor", "debugger"})
_TASK_ID_RE = re.compile(r"(?im)^\s*Task(?:[- ]ID)?:\s*(task-[a-z0-9]+)\s*$")
_MODE_RE = re.compile(r"(?im)^\s*Mode:\s*(task|campaign)\s*$")
_WORKTREE_RE = re.compile(r"(?im)^\s*Worktree:\s*(.+?)\s*$")
_BRANCH_RE = re.compile(r"(?im)^\s*\+\s+([^\s]+)\s+\[task\]\s*$")
_SHARED_PLUMBING_MARKERS = (
    "/alembic/",
    "/migrations/",
    "/schema",
    "/schemas/",
    "/contract",
    "/contracts/",
    "/routing",
    "/routes/",
    "/config",
    "/build",
    "/exports",
    "/index.",
    "/utils/",
)


def _is_wake_dispatch_specialist_session(session: object) -> bool:
    request_source = getattr(session, "request_source", None)
    return isinstance(request_source, str) and request_source.startswith("persona_wake:dispatch")


@dataclass(frozen=True)
class SpecialistDispatchRequest:
    mode: str | None
    task_id: str | None


@dataclass(frozen=True)
class SpecialistDispatchPlan:
    event_type: str
    current_branch: str | None = None
    working_dir: str | None = None


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


def _parse_specialist_dispatch_request(task: str) -> SpecialistDispatchRequest:
    """Extract explicit specialist mode and optional task id from a dispatch prompt."""
    mode_match = _MODE_RE.search(task)
    task_match = _TASK_ID_RE.search(task)
    return SpecialistDispatchRequest(
        mode=mode_match.group(1).lower() if mode_match else None,
        task_id=task_match.group(1).lower() if task_match else None,
    )


def _is_shared_plumbing_path(path: str) -> bool:
    lowered = path.lower()
    return any(marker in lowered for marker in _SHARED_PLUMBING_MARKERS)


async def _project_dispatch_overlap_block_reason(
    *,
    project_id: str,
    agent_slug: str,
    mode: str,
    task_id: str | None,
    owners: list[object],
    specialists: list[object],
) -> str | None:
    """Return a blocking reason when live project state makes a new specialist lane unsafe."""
    if mode == "campaign":
        duplicate_campaign = next(
            (
                specialist
                for specialist in specialists
                if getattr(specialist, "agent_slug", None) == agent_slug
                and getattr(specialist, "request_source", None) == "persona_wake:dispatch_campaign"
            ),
            None,
        )
        if duplicate_campaign is not None:
            return (
                f"Dispatch blocked for {project_id}: {agent_slug} already has an active "
                "campaign session in this project. Query or inspect the existing campaign "
                "instead of creating a duplicate lane."
            )

    relevant_specialists = [
        specialist
        for specialist in specialists
        if _is_wake_dispatch_specialist_session(specialist)
        and not (
            mode == "task"
            and getattr(specialist, "agent_slug", None) == agent_slug
            and getattr(specialist, "request_source", None) == "persona_wake:dispatch_campaign"
        )
    ]
    if relevant_specialists:
        specialist = relevant_specialists[0]
        detail = getattr(specialist, "agent_slug", None) or "unknown"
        return (
            f"Dispatch blocked for {project_id}: active specialist {detail} has missing scope "
            "evidence, so parallel same-project coding would be blind overlap risk. Wait, "
            "inspect, or reconcile before dispatching another specialist lane."
        )

    for owner in owners:
        owner_task_id = getattr(owner, "task_id", None)
        if mode == "task" and task_id and owner_task_id == task_id:
            continue

        scope_paths = list(getattr(owner, "scope_paths", []) or [])
        if not scope_paths:
            detail = owner_task_id or getattr(owner, "branch", None) or getattr(owner, "session_id", "unknown")
            return (
                f"Dispatch blocked for {project_id}: live lane {detail} has missing scope evidence. "
                "Do not start another coding lane until scope is known or the lane is reconciled."
            )

        shared_paths = [path for path in scope_paths if _is_shared_plumbing_path(path)]
        if shared_paths:
            return (
                f"Dispatch blocked for {project_id}: live lane touches shared-plumbing paths "
                f"({shared_paths[0]}). Treat migrations, schemas, contracts, routing, build/config, "
                "shared exports, and cross-cutting utilities as blockers to blind parallel coding."
            )

    return None


async def _run_project_st_command(project_id: str, subcommand: str) -> str:
    """Run one st command in the target project root with the project venv active."""
    from app.constants.projects import get_known_roots
    from app.services.tools._executor_bash import run_bash
    from app.services.tools.project_env import build_project_env

    root = get_known_roots().get(project_id)
    working_dir = Path(root or ".").resolve()
    env = build_project_env(working_dir)
    return await run_bash(
        f"st -P {shlex.quote(project_id)} {subcommand}",
        working_dir,
        env,
    )


async def _run_project_command(project_id: str, command: str) -> str:
    """Run a raw shell command in the target project root with the project venv active."""
    from app.constants.projects import get_known_roots
    from app.services.tools._executor_bash import run_bash
    from app.services.tools.project_env import build_project_env

    root = get_known_roots().get(project_id)
    working_dir = Path(root or ".").resolve()
    env = build_project_env(working_dir)
    return await run_bash(command, working_dir, env)


async def _ensure_task_lane_context(
    project_id: str,
    task_id: str,
) -> tuple[str | None, str | None, str | None]:
    """Return (branch, worktree, error) for a claimed task lane, claiming if needed."""
    details = await _run_project_st_command(
        project_id,
        f"checkpoints -d {shlex.quote(task_id)}",
    )
    if "No checkpoint found" in details:
        claim = await _run_project_st_command(project_id, f"claim {shlex.quote(task_id)}")
        if "Error:" in claim or claim.startswith("ERROR"):
            return (None, None, f"Dispatch blocked for {task_id}: {claim.strip()}")
        details = await _run_project_st_command(
            project_id,
            f"checkpoints -d {shlex.quote(task_id)}",
        )

    branch_match = _BRANCH_RE.search(details)
    worktree_match = _WORKTREE_RE.search(details)
    branch = branch_match.group(1).strip() if branch_match else None
    worktree = worktree_match.group(1).strip() if worktree_match else None
    if not branch or not worktree:
        return (
            None,
            None,
            f"Dispatch blocked for {task_id}: unable to resolve claimed branch/worktree from checkpoint details.",
        )
    return (branch, worktree, None)


async def _prepare_specialist_dispatch(
    *,
    db: object,
    project_id: str,
    agent_slug: str,
    task: str,
) -> SpecialistDispatchPlan:
    """Validate specialist dispatch mode and attach task-lane metadata when needed."""
    from app.services.ownership_inventory import (
        query_project_active_specialists,
        query_project_ownership,
    )
    from app.services.tools._executor_io_tasks import (
        _cleanup_dispatch_block_reason,
        _live_dispatch_block_reason,
    )

    request = _parse_specialist_dispatch_request(task)
    if request.mode not in {"task", "campaign"}:
        raise ValueError(
            f"Dispatch blocked for {agent_slug}: include an explicit `Mode: task` or "
            f"`Mode: campaign` line in the dispatch prompt."
        )

    async def _bash_fn(command: str) -> str:
        return await _run_project_command(project_id, command)

    cleanup_block, _ = await _cleanup_dispatch_block_reason(_bash_fn, project_id)
    if cleanup_block:
        raise ValueError(cleanup_block)

    owners = await query_project_ownership(db, project_id)
    specialists = await query_project_active_specialists(db, project_id)
    overlap_block = await _project_dispatch_overlap_block_reason(
        project_id=project_id,
        agent_slug=agent_slug,
        mode=request.mode,
        task_id=request.task_id,
        owners=owners,
        specialists=specialists,
    )
    if overlap_block:
        raise ValueError(overlap_block)

    if request.mode == "campaign":
        return SpecialistDispatchPlan(event_type="dispatch_campaign")

    if not request.task_id:
        raise ValueError(
            f"Dispatch blocked for {agent_slug}: `Mode: task` requires a `Task-ID: task-...` line."
        )

    live_block = await _live_dispatch_block_reason(_bash_fn, request.task_id, project_id)
    if live_block:
        raise ValueError(live_block)

    branch, worktree, lane_error = await _ensure_task_lane_context(project_id, request.task_id)
    if lane_error:
        raise ValueError(lane_error)

    return SpecialistDispatchPlan(
        event_type="dispatch_task",
        current_branch=branch,
        working_dir=worktree,
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
            dispatch_plan = (
                await _prepare_specialist_dispatch(
                    db=db,
                    project_id=project_id,
                    agent_slug=agent_slug,
                    task=task,
                )
                if agent_slug in _SPECIALIST_AGENT_SLUGS
                else SpecialistDispatchPlan(event_type="dispatch")
            )

        dispatch_wake(
            agent_slug=agent_slug,
            model=resolved.model,
            provider=resolved.provider,
            temperature=resolved.agent.temperature,
            prompt=task,
            project_id=project_id,
            event_type=dispatch_plan.event_type,
            thinking_level=resolved.agent.thinking_level,
            max_turns=max_turns,
            parent_session_id=parent_session_id,
            current_branch=dispatch_plan.current_branch,
            working_dir=dispatch_plan.working_dir,
        )
        return _dispatch_result_text(agent_slug, bool(resolved.agent.is_coding_agent), task)
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
