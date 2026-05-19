"""Session task-state helpers for DirectToolExecutor.

Handles stale-session detection, reconciliation, and retirement
of Agent Hub sessions linked to SummitFlow task checkpoints.
"""

from __future__ import annotations

import logging
import re
import shlex
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from app.services._session_metadata_helpers import metadata_paths
from app.services.ownership_lanes import (
    STALE_WORKSTREAM_IDLE_MINUTES,
    idle_minutes_from_timestamps,
    infer_task_id,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.models import Session

_FINAL_TASK_STATUSES = {"blocked", "completed", "cancelled", "abandoned", "failed"}
_MISSING_CHECKPOINT_PHRASE = "No checkpoint found"
_RETIRE_NOTE = "Retired via task lane retire action"
_NO_CHECKPOINT_MERGE_PHRASE = "completed without checkpoint merge"
_NO_CODE_CHANGES_PHRASE = "no files changed vs base branch"
_STATUS_UPDATE_FAILED_PHRASE = "work published but status update failed"
_ADMIN_RECOVERY_PHRASE = "recovery: st done"
_EXEC_LOG_RECENT_MINUTES = 5
_TASK_SESSION_LOOKBACK_HOURS = 48
_EXEC_LOG_ACTIVE_MARKERS = (
    "Verification failed",
    "Self-heal attempt",
    "Calling agent for fix attempt",
    "Starting autonomous execution",
    "Running pristine check",
    "Task branch ready in shared checkout:",
)
_EXEC_LOG_LINE_RE = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\|")


def _session_matches_task_lane(session: Session, task_id: str) -> bool:
    metadata = session.provider_metadata if isinstance(session.provider_metadata, dict) else {}
    return infer_task_id(session.external_id, session.current_branch, *metadata_paths(metadata)) == task_id


async def _load_task_lane_sessions(task_id: str) -> list[Session]:
    """Load recent Agent Hub sessions linked to a task checkpoint."""
    from sqlalchemy import or_, select

    from app.db import async_session
    from app.models import Session

    async with async_session() as db:
        query = (
            select(Session)
            .where(
                or_(
                    Session.external_id == task_id,
                    Session.current_branch == task_id,
                    Session.current_branch.like(f"{task_id}/%"),
                ),
                Session.agent_slug.isnot(None),
            )
            .order_by(Session.created_at.desc())
            .limit(20)
        )
        sessions = list((await db.execute(query)).scalars().all())
        if sessions:
            return sessions

        fallback_query = (
            select(Session)
            .where(
                Session.created_at >= datetime.now(UTC) - timedelta(hours=_TASK_SESSION_LOOKBACK_HOURS),
                or_(
                    Session.agent_slug.isnot(None),
                    Session.session_type.in_(("agent", "claude_code")),
                ),
            )
            .order_by(Session.created_at.desc())
            .limit(200)
        )
        candidates = list((await db.execute(fallback_query)).scalars().all())
        return [session for session in candidates if _session_matches_task_lane(session, task_id)][:20]


def _choose_authoritative_session(completed_sessions: list[Session]) -> Session:
    """Pick the completed session that should become authoritative."""
    return max(
        completed_sessions,
        key=lambda s: (
            getattr(s, "created_at", datetime.min.replace(tzinfo=UTC)),
            bool(getattr(s, "summary_oneliner", None)),
        ),
    )


def _normalize_summary(summary: str | None) -> str:
    text = (summary or "completed work").strip()
    return " ".join(text.split()) or "completed work"


def _extract_task_status(context_output: str) -> str | None:
    """Extract task status from `st context --compact` output."""
    if not isinstance(context_output, str):
        return None
    first_line = context_output.splitlines()[0] if context_output else ""
    match = re.match(r"^TASK:[^|]+\|([^|]+)\|", first_line)
    if not match:
        return None
    return match.group(1).strip().lower() or None


def _task_is_final(task_status: str | None) -> bool:
    return bool(task_status and task_status in _FINAL_TASK_STATUSES)


from app.services.tools._tool_constants import st_cmd as _st_cmd  # noqa: E402


async def _get_task_status(
    bash_fn: Callable[..., Awaitable[str]],
    task_id: str,
    project_id: str | None,
) -> str | None:
    """Load current SummitFlow task status through the CLI."""
    try:
        output = await bash_fn(_st_cmd(f"context {shlex.quote(task_id)} --compact", project_id))
    except Exception:
        logger.exception("Failed to load task context for stale-session check", extra={"task_id": task_id})
        return None
    return _extract_task_status(output)


async def _task_has_checkpoint(
    bash_fn: Callable[..., Awaitable[str]],
    task_id: str,
    project_id: str | None,
) -> bool | None:
    """Return whether SummitFlow reports an active checkpoint for the task."""
    try:
        output = await bash_fn(_st_cmd(f"checkpoints --details {shlex.quote(task_id)}", project_id))
    except Exception:
        logger.exception("Failed to inspect checkpoints for stale-session recovery", extra={"task_id": task_id})
        return None
    return _MISSING_CHECKPOINT_PHRASE not in output


async def _has_recent_execution_activity(
    bash_fn: Callable[..., Awaitable[str]],
    task_id: str,
    project_id: str | None,
    *,
    now: datetime | None = None,
) -> bool:
    """Return whether the task shows recent execution activity that should block reconcile closure."""
    try:
        output = await bash_fn(_st_cmd(f"exec-log {shlex.quote(task_id)} -n 40 --debug", project_id))
    except Exception:
        logger.exception("Failed to inspect execution log for reconcile guard", extra={"task_id": task_id})
        return False

    current = now or datetime.now()
    for raw_line in output.splitlines():
        if not any(marker in raw_line for marker in _EXEC_LOG_ACTIVE_MARKERS):
            continue
        match = _EXEC_LOG_LINE_RE.match(raw_line)
        if not match:
            continue
        try:
            event_time = datetime.fromisoformat(match.group("ts"))
        except ValueError:
            continue
        age_seconds = (current - event_time).total_seconds()
        if 0 <= age_seconds <= _EXEC_LOG_RECENT_MINUTES * 60:
            return True
    return False


async def _recover_orphan_running_task(
    bash_fn: Callable[..., Awaitable[str]],
    task_id: str,
    project_id: str | None,
    task_status: str | None,
) -> str | None:
    """Recover a task stuck in running with no session-backed checkpoint evidence."""
    if task_status != "running":
        return None
    has_checkpoint = await _task_has_checkpoint(bash_fn, task_id, project_id)
    if has_checkpoint is not False:
        return None

    reason = "Recovered stale running task with no linked Agent Hub sessions or checkpoint."
    cmd = _st_cmd(f"cancel {shlex.quote(task_id)} -r {shlex.quote(reason)}", project_id)
    result = await bash_fn(cmd)
    return (
        f"{result}\n"
        f"Recovered {task_id}: task was running but had no linked Agent Hub sessions and no active checkpoint."
    )


async def _cleanup_explicit_lane(
    bash_fn: Callable[..., Awaitable[str]],
    task_id: str,
    project_id: str | None,
) -> str:
    """Run safe checkpoint cleanup after session-driven task retirement/finalize."""
    result = await bash_fn(_st_cmd("cleanup checkpoints --auto", project_id))
    cleaned = result.strip()
    if cleaned:
        return cleaned
    return f"Checkpoint cleanup returned no output for {task_id}."


async def _mark_stale_active_sessions(
    sessions: list[Session],
    *,
    workstream_status: str,
    note_prefix: str,
    only_if_stale: bool = True,
) -> int:
    """Convert stale active sessions into completed sessions with lifecycle markers."""
    from app.db import async_session

    stale_active = [
        s
        for s in sessions
        if s.status == "active"
        and (
            not only_if_stale
            or idle_minutes_from_timestamps(
                created_at=s.created_at,
                updated_at=getattr(s, "updated_at", None),
                workstream_updated_at=getattr(s, "workstream_updated_at", None),
            )
            >= STALE_WORKSTREAM_IDLE_MINUTES
        )
    ]
    if not stale_active:
        return 0

    now = datetime.now(UTC)
    async with async_session() as db:
        from app.services.session_live_activity import mark_session_completed

        for session in stale_active:
            branch = getattr(session, "current_branch", None) or "unknown branch"
            idle_minutes = idle_minutes_from_timestamps(
                created_at=session.created_at,
                updated_at=getattr(session, "updated_at", None),
                workstream_updated_at=getattr(session, "workstream_updated_at", None),
                now=now,
            )
            note = f"{note_prefix} after {idle_minutes}m inactivity ({branch})"
            mark_session_completed(session, summary=note, termination_reason=f"cleanup_closed:{workstream_status}")
            session.workstream_status = workstream_status
            session.workstream_note = note
            session.workstream_updated_at = now
            db.add(session)
        await db.commit()
    return len(stale_active)


async def _persist_workstream_resolution(
    sessions: list[Session],
    authoritative_session: Session,
) -> None:
    """Persist authoritative/superseded markers for a reconciled task checkpoint."""
    from app.db import async_session

    now = datetime.now(UTC)
    winner_branch = getattr(authoritative_session, "current_branch", None) or "unknown"

    async with async_session() as db:
        for session in sessions:
            if session is authoritative_session:
                session.workstream_status = "authoritative"
                session.workstream_note = "Selected as authoritative during reconcile"
            else:
                session.workstream_status = "superseded"
                session.workstream_note = (
                    f"Superseded by session on branch {winner_branch} during reconcile"
                )
            session.workstream_updated_at = now
            db.add(session)
        await db.commit()


async def _mark_lane_residue(
    sessions: list[Session],
    *,
    workstream_status: str,
    note: str,
) -> None:
    """Persist a uniform residue marker across all linked sessions."""
    from app.db import async_session

    now = datetime.now(UTC)
    async with async_session() as db:
        for session in sessions:
            session.workstream_status = workstream_status
            session.workstream_note = note
            session.workstream_updated_at = now
            db.add(session)
        await db.commit()


async def _retire_stale_active_sessions(
    bash_fn: Callable[..., Awaitable[str]],
    task_id: str,
    project_id: str | None,
    sessions: list[Session],
    workstream_status: str,
    stale_prefix: str,
    terminal_prefix: str,
) -> tuple[list[Session], list[Session], str | None]:
    """Retire stale/active sessions; return updated sessions, active remainder, and last task_status."""
    active_sessions = [s for s in sessions if s.status == "active"]
    task_status: str | None = None
    if not active_sessions:
        return sessions, active_sessions, task_status

    retired = await _mark_stale_active_sessions(
        sessions, workstream_status=workstream_status, note_prefix=stale_prefix,
    )
    if retired:
        sessions = await _load_task_lane_sessions(task_id)
        active_sessions = [s for s in sessions if s.status == "active"]

    task_status = await _get_task_status(bash_fn, task_id, project_id)
    if active_sessions and _task_is_final(task_status):
        retired = await _mark_stale_active_sessions(
            sessions,
            workstream_status=workstream_status,
            note_prefix=f"{terminal_prefix} because task is {task_status}",
            only_if_stale=False,
        )
        if retired:
            sessions = await _load_task_lane_sessions(task_id)
            active_sessions = [s for s in sessions if s.status == "active"]

    return sessions, active_sessions, task_status


# ---------------------------------------------------------------------------
# Reconcile helpers
# ---------------------------------------------------------------------------


def _needs_admin_close(result: str) -> bool:
    """Return True when `st done` explicitly prints an admin recovery hint."""
    lowered = result.lower()
    return (
        _STATUS_UPDATE_FAILED_PHRASE in lowered
        and _ADMIN_RECOVERY_PHRASE in lowered
        and "--admin" in lowered
    )


def _needs_manual_closeout(result: str) -> bool:
    """Return True when session evidence is insufficient for autonomous closeout."""
    lowered = result.lower()
    return (
        (_MISSING_CHECKPOINT_PHRASE.lower() in lowered and "was it claimed?" in lowered)
        or "claimed checkout has uncommitted changes." in lowered
        or "claimed checkpoint has uncommitted changes." in lowered
    )


async def _cleanup_terminal_residue(
    bash_fn: Callable[..., Awaitable[str]],
    task_id: str,
    project_id: str | None,
    result: str,
) -> str:
    """Run safe cleanup when result contains terminal closeout-residue text."""
    lowered = result.lower()
    if (
        "cannot merge - task" not in lowered
        and "failed to merge " not in lowered
        and _NO_CHECKPOINT_MERGE_PHRASE not in lowered
    ):
        return result
    task_status = await _get_task_status(bash_fn, task_id, project_id)
    if _task_is_final(task_status):
        cleanup_result = await _cleanup_explicit_lane(bash_fn, task_id, project_id)
        return f"{result.rstrip()}\nCheckpoint cleanup: {cleanup_result}"
    return result


async def _retire_noop_lane(
    bash_fn: Callable[..., Awaitable[str]],
    task_id: str,
    project_id: str | None,
    sessions: list[Session],
    result: str,
) -> str:
    """Retire task residue whose diff gate found no code changes vs the base branch."""
    note = (
        "Retired during reconcile after diff gate reported no code changes; "
        "task remains open for a real implementation or explicit closure."
    )
    await _mark_lane_residue(sessions, workstream_status="retired", note=note)
    cleanup_result = await _cleanup_explicit_lane(bash_fn, task_id, project_id)
    return (
        f"Reconcile retired no-op task residue for {task_id}: diff gate reported no files changed "
        "vs base branch, so the completed session residue was closed and the task "
        "was left open.\n"
        f"Original result: {result.strip()}\n"
        f"Checkpoint cleanup: {cleanup_result}"
    )


def _no_completed_sessions_message(
    task_id: str,
    sessions: list[Session],
    task_status: str | None,
) -> str:
    """Build the reconcile-skip message when no completed sessions are available."""
    statuses = ", ".join(sorted({str(s.status) for s in sessions if s.status}))
    task_detail = f" (task={task_status})" if task_status else ""
    next_step = (
        ' Treat this as queue/checkpoint state, not closure residue. '
        'Use `st context`, `st sessions`, and `st pulse` to keep the project moving.'
        if task_status == "blocked"
        else ""
    )
    return (
        f"Reconcile skipped for {task_id}: no completed sessions to justify closure "
        f"(statuses={statuses or 'unknown'}){task_detail}.{next_step}"
    )


async def _dispatch_done(
    bash_fn: Callable[..., Awaitable[str]],
    task_id: str,
    project_id: str | None,
    message: str,
    sessions: list[Session],
) -> str:
    """Run `st done` and handle explicit recovery and no-op residue paths."""
    cmd = _st_cmd(f"done {shlex.quote(task_id)} --message {shlex.quote(message)}", project_id)
    result = await bash_fn(cmd)
    if "Task not ready to complete:" in result:
        return (
            f"Reconcile stopped for {task_id}: SummitFlow reported the task is not ready to "
            "complete. Do not admin-close it from session evidence. "
            "Inspect task context/verification and keep the task open.\n"
            f"Original result: {result.strip()}"
        )
    if _NO_CODE_CHANGES_PHRASE in result.lower():
        return await _retire_noop_lane(bash_fn, task_id, project_id, sessions, result)
    if _needs_manual_closeout(result):
        return (
            f"Reconcile stopped for {task_id}: SummitFlow needs direct task context "
            "before closeout can continue. Do not admin-close it from session evidence. "
            "Inspect task context/verification and keep the task open.\n"
            f"Original result: {result.strip()}"
        )
    if _needs_admin_close(result):
        admin_cmd = _st_cmd(
            f"done {shlex.quote(task_id)} --admin --message {shlex.quote(message)}",
            project_id,
        )
        admin_result = await bash_fn(admin_cmd)
        return await _cleanup_terminal_residue(bash_fn, task_id, project_id, admin_result)
    return await _cleanup_terminal_residue(bash_fn, task_id, project_id, result)


# ---------------------------------------------------------------------------
# Session-backed task lifecycle: retire and reconcile
# ---------------------------------------------------------------------------


async def _retire_task_lane(
    bash_fn: Callable[..., Awaitable[str]],
    task_id: str,
    project_id: str | None,
) -> str:
    """Persist a retired marker for task residue when no live sessions remain."""
    from app.db import async_session

    sessions = await _load_task_lane_sessions(task_id)
    if not sessions:
        return f"Retire skipped for {task_id}: no linked Agent Hub sessions found."

    sessions, active_sessions, task_status = await _retire_stale_active_sessions(
        bash_fn, task_id, project_id, sessions,
        workstream_status="retired",
        stale_prefix="Retired stale active session during retire_lane",
        terminal_prefix="Retired stale active session",
    )
    if active_sessions:
        task_detail = f" (task={task_status})" if task_status else ""
        return (
            f"Retire blocked for {task_id}: cannot retire while {len(active_sessions)} "
            f"active session(s) remain{task_detail}."
        )

    now = datetime.now(UTC)
    async with async_session() as db:
        for session in sessions:
            session.workstream_status = "retired"
            if not getattr(session, "workstream_note", None):
                session.workstream_note = _RETIRE_NOTE
            session.workstream_updated_at = now
            db.add(session)
        await db.commit()
    cleanup_result = await _cleanup_explicit_lane(bash_fn, task_id, project_id)
    return (
        f"Retired {len(sessions)} session-backed checkpoint record(s) for {task_id}\n"
        f"Checkpoint cleanup: {cleanup_result}"
    )


async def _reconcile_task_lane(
    bash_fn: Callable[..., Awaitable[str]],
    task_id: str,
    project_id: str | None,
) -> str:
    """Reconcile a task using Agent Hub session evidence."""
    sessions = await _load_task_lane_sessions(task_id)
    if not sessions:
        task_status = await _get_task_status(bash_fn, task_id, project_id)
        orphan = await _recover_orphan_running_task(bash_fn, task_id, project_id, task_status)
        return orphan or (
            f"Reconcile skipped for {task_id}: no linked Agent Hub sessions found. "
            "Use `st context` and `st session-events` first."
        )

    sessions, active_sessions, task_status = await _retire_stale_active_sessions(
        bash_fn, task_id, project_id, sessions,
        workstream_status="superseded",
        stale_prefix="Marked stale active during reconcile",
        terminal_prefix="Marked stale active during reconcile",
    )
    if active_sessions:
        task_detail = f" (task={task_status})" if task_status else ""
        return (
            f"Reconcile blocked for {task_id}: still has {len(active_sessions)} active "
            f"session(s){task_detail}. Verify whether the session is truly stale before closing it."
        )

    completed_sessions = [
        s for s in sessions
        if s.status == "completed" and getattr(s, "workstream_status", None) != "superseded"
    ]
    if not completed_sessions:
        if task_status is None:
            task_status = await _get_task_status(bash_fn, task_id, project_id)
        return _no_completed_sessions_message(task_id, sessions, task_status)

    if await _has_recent_execution_activity(bash_fn, task_id, project_id):
        return (
            f"Reconcile stopped for {task_id}: SummitFlow execution log shows recent autonomous "
            "activity. Do not close the task from session evidence while execution/self-heal is "
            "still active or just resumed."
        )

    authoritative_session = _choose_authoritative_session(completed_sessions)
    await _persist_workstream_resolution(sessions, authoritative_session)
    summary = _normalize_summary(getattr(authoritative_session, "summary_oneliner", None))
    message = f"Reconciled from Agent Hub session evidence: {summary}"
    return await _dispatch_done(bash_fn, task_id, project_id, message, sessions)


# ---------------------------------------------------------------------------
# Thin action dispatchers shared by manage_tasks
# ---------------------------------------------------------------------------


async def _handle_lane_action(
    bash_fn: Callable[..., Awaitable[str]],
    action: str,
    task_id: str | None,
    project_id: str | None,
) -> str:
    """Handle reconcile/retire_lane actions with task_id guard."""
    if not task_id:
        return f"Error: task_id required for {action}"
    handler = _reconcile_task_lane if action == "reconcile" else _retire_task_lane
    return await handler(bash_fn, task_id, project_id)


async def _handle_simple_task_action(
    bash_fn: Callable[..., Awaitable[str]],
    action: str,
    task_id: str | None,
    project_id: str | None,
) -> str:
    """Handle done/abandon/cancel with task_id guard and done no-code-changes fallback."""
    if not task_id:
        return f"Error: task_id required for {action}"
    result = await bash_fn(_st_cmd(f"{action} {shlex.quote(task_id)}", project_id))
    if action == "done" and _NO_CODE_CHANGES_PHRASE in result.lower():
        sessions = await _load_task_lane_sessions(task_id)
        if sessions:
            has_retired_lane = any(
                getattr(session, "workstream_status", None) == "retired"
                for session in sessions
            )
            fallback_handler = _retire_task_lane if has_retired_lane else _reconcile_task_lane
            fallback = await fallback_handler(bash_fn, task_id, project_id)
            return f"{result.rstrip()}\nFallback: {fallback}"
    return result
