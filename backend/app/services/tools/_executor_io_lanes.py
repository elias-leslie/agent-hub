"""Session lane management helpers for DirectToolExecutor.

Handles stale-lane detection, reconciliation, and retirement
of Agent Hub sessions linked to SummitFlow task lanes.
"""

from __future__ import annotations

import logging
import re
import shlex
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.services.ownership_lanes import (
    STALE_WORKSTREAM_IDLE_MINUTES,
    idle_minutes_from_timestamps,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.models import Session

_TERMINAL_TASK_STATUSES = {"blocked", "completed", "cancelled", "abandoned", "failed"}
_MISSING_CHECKPOINT_PHRASE = "No checkpoint found"
_RETIRE_NOTE = 'Retired via manage_tasks(action="retire_lane")'
_NO_CHECKPOINT_MERGE_PHRASE = "completed without checkpoint merge"
_NO_CODE_CHANGES_PHRASE = "no files changed vs base branch"
_STATUS_UPDATE_FAILED_PHRASE = "code merged but status update failed"
_ADMIN_RECOVERY_PHRASE = "recovery: st done"
_EXEC_LOG_RECENT_MINUTES = 5
_EXEC_LOG_ACTIVE_MARKERS = (
    "Verification failed",
    "Self-heal attempt",
    "Calling agent for fix attempt",
    "Starting autonomous execution",
    "Running pristine check",
    "Worktree ready:",
)
_EXEC_LOG_LINE_RE = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\|")


async def _load_task_lane_sessions(task_id: str) -> list[Session]:
    """Load recent Agent Hub sessions linked to a task lane."""
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
        return list((await db.execute(query)).scalars().all())


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
    import re
    if not isinstance(context_output, str):
        return None
    first_line = context_output.splitlines()[0] if context_output else ""
    match = re.match(r"^TASK:[^|]+\|([^|]+)\|", first_line)
    if not match:
        return None
    return match.group(1).strip().lower() or None


def _task_is_terminal(task_status: str | None) -> bool:
    return bool(task_status and task_status in _TERMINAL_TASK_STATUSES)


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
        logger.exception("Failed to load task context for stale-lane check", extra={"task_id": task_id})
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
        logger.exception("Failed to inspect checkpoints for stale-lane recovery", extra={"task_id": task_id})
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
    """Recover a task stuck in running with no session-backed lane evidence."""
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
            mark_session_completed(
                session,
                summary=f"{note_prefix} after {idle_minutes}m inactivity ({branch})",
                termination_reason=f"cleanup_closed:{workstream_status}",
            )
            session.workstream_status = workstream_status
            session.workstream_note = f"{note_prefix} after {idle_minutes}m inactivity ({branch})"
            session.workstream_updated_at = now
            db.add(session)
        await db.commit()
    return len(stale_active)


async def _persist_workstream_resolution(
    sessions: list[Session],
    authoritative_session: Session,
) -> None:
    """Persist authoritative/superseded markers for a reconciled task lane."""
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
    """Persist a uniform residue marker across all lane sessions."""
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
    """Retire stale/terminal active sessions; return updated sessions, active remainder, and last task_status."""
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
    if active_sessions and _task_is_terminal(task_status):
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


async def _retire_task_lane(
    bash_fn: Callable[..., Awaitable[str]],
    task_id: str,
    project_id: str | None,
) -> str:
    """Persist a retired marker for a task lane when no live sessions remain."""
    from app.db import async_session

    sessions = await _load_task_lane_sessions(task_id)
    if not sessions:
        return f"Retire skipped for {task_id}: no linked Agent Hub sessions found."

    sessions, active_sessions, task_status = await _retire_stale_active_sessions(
        bash_fn, task_id, project_id, sessions,
        workstream_status="retired",
        stale_prefix="Retired stale active lane during retire_lane",
        terminal_prefix="Retired stale active lane",
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
    return f"Retired {len(sessions)} session-backed lane(s) for {task_id}"


async def _reconcile_task_lane(
    bash_fn: Callable[..., Awaitable[str]],
    task_id: str,
    project_id: str | None,
) -> str:
    """Reconcile a task lane using Agent Hub session evidence."""
    from ._executor_io_tasks import _handle_finalize_merge

    async def _finalize_if_terminal_merge_residue(result: str) -> str:
        lowered = result.lower()
        if (
            "cannot merge - task" not in lowered
            and "failed to merge " not in lowered
            and _NO_CHECKPOINT_MERGE_PHRASE not in lowered
        ):
            return result
        task_status = await _get_task_status(bash_fn, task_id, project_id)
        if _task_is_terminal(task_status):
            return await _handle_finalize_merge(bash_fn, task_id, project_id)
        return result

    def _needs_admin_close(result: str) -> bool:
        lowered = result.lower()
        return (
            (_MISSING_CHECKPOINT_PHRASE.lower() in lowered and "was it claimed?" in lowered)
            or "claimed worktree has uncommitted changes." in lowered
            or (_STATUS_UPDATE_FAILED_PHRASE in lowered and _ADMIN_RECOVERY_PHRASE in lowered and "--admin" in lowered)
        )

    async def _retire_noop_lane(result: str) -> str:
        note = (
            "Retired during reconcile after diff gate reported no code changes; "
            "task remains open for a real implementation or explicit closure."
        )
        await _mark_lane_residue(
            sessions,
            workstream_status="retired",
            note=note,
        )
        return (
            f"Reconcile retired no-op lane for {task_id}: diff gate reported no files changed "
            "vs base branch, so the completed session lane was closed as residue and the task "
            "was left open.\n"
            f"Original result: {result.strip()}"
        )

    sessions = await _load_task_lane_sessions(task_id)
    if not sessions:
        task_status = await _get_task_status(bash_fn, task_id, project_id)
        recovered = await _recover_orphan_running_task(bash_fn, task_id, project_id, task_status)
        if recovered:
            return recovered
        return (
            f"Reconcile skipped for {task_id}: no linked Agent Hub sessions found. "
            "Use manage_tasks(action=\"get_context\") or query_sessions() first."
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
            f"session(s){task_detail}. Verify whether the lane is truly stale before closing it."
        )

    completed_sessions = [
        s for s in sessions
        if s.status == "completed" and getattr(s, "workstream_status", None) != "superseded"
    ]
    if not completed_sessions:
        if task_status is None:
            task_status = await _get_task_status(bash_fn, task_id, project_id)
        statuses = ", ".join(sorted({str(s.status) for s in sessions if s.status}))
        task_detail = f" (task={task_status})" if task_status else ""
        next_step = (
            ' Treat this as queue/worktree state, not closure residue. '
            'Use manage_tasks(action="get_context") and cleanup_status/dispatch to keep the project moving.'
            if task_status == "blocked"
            else ""
        )
        return (
            f"Reconcile skipped for {task_id}: no completed sessions to justify closure "
            f"(statuses={statuses or 'unknown'}){task_detail}.{next_step}"
        )

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

    cmd = _st_cmd(f"done {shlex.quote(task_id)} --message {shlex.quote(message)}", project_id)
    result = await bash_fn(cmd)
    if "Task not ready to complete:" in result:
        return (
            f"Reconcile stopped for {task_id}: SummitFlow reported the task is not ready to "
            "complete. Do not admin-close it from session evidence. "
            'Inspect task context/verification and keep the lane open.\n'
            f"Original result: {result.strip()}"
        )
    if _NO_CODE_CHANGES_PHRASE in result.lower():
        return await _retire_noop_lane(result)
    if _needs_admin_close(result):
        admin_cmd = _st_cmd(
            f"done {shlex.quote(task_id)} --admin --message {shlex.quote(message)}",
            project_id,
        )
        admin_result = await bash_fn(admin_cmd)
        return await _finalize_if_terminal_merge_residue(admin_result)
    return await _finalize_if_terminal_merge_residue(result)
