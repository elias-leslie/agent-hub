"""Task creation, dispatch, and cleanup helpers for DirectToolExecutor."""

from __future__ import annotations

import json
import logging
import shlex
import tempfile
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from app.services.cleanup_summary import build_actionable_cleanup_summary
from app.services.ownership_lanes import (
    STALE_WORKSTREAM_IDLE_MINUTES,
    idle_minutes_from_timestamps,
)

logger = logging.getLogger(__name__)
_CANONICAL_TASK_ID_PREFIX = "task-"


from app.services.tools._tool_constants import st_cmd as _st_cmd  # noqa: E402


def _build_plan_json(
    title: str,
    description: str | None,
    done_when: list[str] | None,
    labels: str | None,
    complexity: str | None,
    subtasks: list[dict[str, object]] | None = None,
    # Deprecated params — accepted but ignored for backwards compatibility
    objective: str | None = None,
    spirit_anti: str | None = None,
) -> str:
    """Write a plan JSON to a temp file and return its path."""
    plan: dict[str, object] = {
        "title": title,
        "complexity": complexity or "STANDARD",
        "autonomous": True,
    }
    if description:
        plan["description"] = description
    if done_when:
        plan["done_when"] = done_when
    if labels:
        plan["labels"] = labels.split(",")
    if subtasks:
        plan["subtasks"] = subtasks

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, prefix="st-plan-"
    ) as f:
        json.dump(plan, f)
        return f.name


async def _handle_create(
    bash_fn: Callable[..., Awaitable[str]],
    title: str,
    description: str | None,
    priority: int,
    task_type: str,
    labels: str | None,
    project_id: str | None,
    done_when: list[str] | None,
    complexity: str | None,
    subtasks: list[dict[str, object]] | None = None,
    # Deprecated params — accepted but ignored for backwards compatibility
    objective: str | None = None,
    spirit_anti: str | None = None,
) -> str:
    """Handle task creation — plan-based or basic."""
    if done_when or subtasks:
        tmpfile = _build_plan_json(
            title, description, done_when, labels, complexity,
            subtasks=subtasks,
        )
        cmd = _st_cmd(f"create --plan {shlex.quote(tmpfile)}", project_id)
        logger.info("manage_tasks create via plan: %s", cmd)
        return await bash_fn(cmd)

    sub = f"create {shlex.quote(title)} -t {shlex.quote(task_type)} -p {priority}"
    if description:
        sub += f" -d {shlex.quote(description)}"
    if labels:
        sub += f" -l {shlex.quote(labels)}"
    cmd = _st_cmd(sub, project_id)
    logger.info("manage_tasks create: %s", cmd)
    return await bash_fn(cmd)


async def _build_dispatch_warning(
    bash_fn: Callable[..., Awaitable[str]],
    project_id: str | None,
    cleanup_status: str | None = None,
) -> str:
    """Return a warning string if tasks are already running, else empty string."""
    try:
        warnings: list[str] = []
        running_json = await bash_fn(_st_cmd("list --status running --json", project_id))
        running: list[dict[str, str]] = (
            json.loads(running_json) if running_json.strip() else []
        )
        project_label = f" in {project_id}" if project_id else ""
        if running:
            ids = ", ".join(t.get("id", "?") for t in running[:5])
            warnings.append(
                f"WARNING: {len(running)} task(s) already running"
                f"{project_label}: {ids}. "
                "Risk of merge conflicts."
            )
        if project_id:
            cleanup_status = cleanup_status or await bash_fn(_st_cmd("cleanup status", project_id))
            if " finalize:" in cleanup_status:
                warnings.append(
                    "WARNING: merge-ready residue detected in cleanup status. "
                    "Prefer finalize_merge, reconcile, or cleanup_worktrees when convenient."
                )
        return "\n\n".join(warnings) + ("\n\n" if warnings else "")
    except Exception:
        return ""  # Never block dispatch on warning failure


async def _cleanup_dispatch_block_reason(
    bash_fn: Callable[..., Awaitable[str]],
    project_id: str | None,
) -> tuple[str | None, str | None]:
    """Return a blocking reason when cleanup residue should stop new dispatches."""
    if not project_id:
        return (None, None)
    try:
        cleanup_status = await bash_fn(_st_cmd("cleanup status", project_id))
    except Exception:
        return (None, None)
    # Plain finalize residue means a merge-ready branch exists, which should warn
    # but not freeze unrelated dispatches across the whole project.
    if " conflicts:" in cleanup_status or " review:" in cleanup_status:
        actionable = build_actionable_cleanup_summary(cleanup_status)
        detail = f"\n\n{actionable}" if actionable else ""
        return (
            "Dispatch blocked: unresolved cleanup residue detected in cleanup status. "
            "Use finalize_merge, reconcile, or cleanup_worktrees before dispatching more work."
            f"{detail}"
        ), cleanup_status
    return None, cleanup_status


async def _live_dispatch_block_reason(
    bash_fn: Callable[..., Awaitable[str]],
    task_id: str,
    project_id: str | None,
) -> str | None:
    """Return a blocking reason when same-task live state says to wait or reconcile."""
    if not project_id or not task_id.startswith(_CANONICAL_TASK_ID_PREFIX):
        return None

    from ._executor_io_lanes import (
        _get_task_status,
        _has_recent_execution_activity,
        _load_task_lane_sessions,
    )

    task_status = await _get_task_status(bash_fn, task_id, project_id)
    sessions = await _load_task_lane_sessions(task_id)
    active_sessions = [session for session in sessions if getattr(session, "status", None) == "active"]
    task_detail = f" (task={task_status})" if task_status else ""

    if active_sessions:
        now = datetime.now(UTC)
        freshest_idle = min(
            idle_minutes_from_timestamps(
                created_at=getattr(session, "created_at", None),
                updated_at=getattr(session, "updated_at", None),
                workstream_updated_at=getattr(session, "workstream_updated_at", None),
                now=now,
            )
            for session in active_sessions
        )
        if freshest_idle < STALE_WORKSTREAM_IDLE_MINUTES:
            return (
                f"Dispatch blocked for {task_id}: same task already has {len(active_sessions)} "
                f"active session(s){task_detail} with fresh progress ({freshest_idle}m idle). "
                "Wait or monitor the current lane instead of redispatching."
            )
        return (
            f"Dispatch blocked for {task_id}: same task still has {len(active_sessions)} "
            f"stale active session(s){task_detail} ({freshest_idle}m idle). "
            "Inspect or reconcile the current lane before dispatching again."
        )

    if task_status == "running":
        if await _has_recent_execution_activity(bash_fn, task_id, project_id):
            return (
                f"Dispatch blocked for {task_id}: task is already running and shows recent "
                "autonomous activity. Wait or inspect the current lane instead of redispatching."
            )
        return (
            f"Dispatch blocked for {task_id}: task is already running{task_detail} without fresh "
            "session evidence. Inspect or reconcile the current lane before dispatching again."
        )

    return None


async def _handle_dispatch(
    bash_fn: Callable[..., Awaitable[str]],
    task_id: str,
    project_id: str | None,
) -> str:
    """Dispatch a task via autocode, prefixed with any running-task warning."""
    block_reason, cleanup_status = await _cleanup_dispatch_block_reason(bash_fn, project_id)
    if block_reason:
        return block_reason
    live_block = await _live_dispatch_block_reason(bash_fn, task_id, project_id)
    if live_block:
        return live_block
    warning = await _build_dispatch_warning(bash_fn, project_id, cleanup_status=cleanup_status)
    result = await bash_fn(_st_cmd(f"autocode {shlex.quote(task_id)}", project_id))
    return warning + result


async def _handle_cleanup_status(
    bash_fn: Callable[..., Awaitable[str]], project_id: str | None,
) -> str:
    """Return canonical cleanup status for a concrete project."""
    if not project_id:
        return 'Error: project_id required for cleanup_status'
    cleanup_status = await bash_fn(_st_cmd("cleanup status", project_id))
    actionable = build_actionable_cleanup_summary(cleanup_status)
    return f"{cleanup_status}\n\n{actionable}" if actionable else cleanup_status


async def _handle_cleanup_worktrees(
    bash_fn: Callable[..., Awaitable[str]], project_id: str | None,
) -> str:
    """Safely clean worktrees for a concrete project."""
    if not project_id:
        return 'Error: project_id required for cleanup_worktrees'
    cleanup_status = await bash_fn(_st_cmd("cleanup status", project_id))
    actionable = build_actionable_cleanup_summary(cleanup_status)
    header = cleanup_status.splitlines()[0] if cleanup_status else ""
    has_active_worktrees = "worktrees=0" not in header
    has_branch_residue = "orphan=0" not in header or "prunable=0" not in header
    if not has_active_worktrees and not has_branch_residue:
        return f"{cleanup_status}\n\nCleanup complete for {project_id}."
    result = await bash_fn(_st_cmd("cleanup worktrees --auto", project_id))
    return f"{result}\n\n{actionable}" if actionable else result


async def _handle_cleanup_salvage_orphan(
    bash_fn: Callable[..., Awaitable[str]], task_id: str | None, project_id: str | None,
) -> str:
    """Recover a missing-task salvage candidate into a normal task lane."""
    if not task_id:
        return "Error: task_id required for salvage_orphan"
    if not project_id:
        return "Error: project_id required for salvage_orphan"
    return await bash_fn(_st_cmd(f"cleanup salvage {shlex.quote(task_id)}", project_id))


async def _handle_cleanup_all_safe(
    bash_fn: Callable[..., Awaitable[str]],
) -> str:
    """Exhaust safe cleanup across all managed projects in one canonical call."""
    before = await bash_fn("st cleanup status --all")
    cleanup_result = await bash_fn("st cleanup worktrees --auto --all")
    after = await bash_fn("st cleanup status --all")
    actionable = build_actionable_cleanup_summary(after)
    parts = [before, cleanup_result, after]
    if actionable:
        parts.append(actionable)
    return "\n\n".join(part for part in parts if part)


async def _handle_smart_sync(
    bash_fn: Callable[..., Awaitable[str]],
    project_id: str | None,
) -> str:
    """Publish one project's coherent repo state via the canonical smart-sync path."""
    if not project_id:
        return "Error: project_id required for smart_sync"
    return await bash_fn(f"st git smart-sync {shlex.quote(project_id)}")


async def _handle_finalize_merge(
    bash_fn: Callable[..., Awaitable[str]],
    task_id: str | None,
    project_id: str | None,
) -> str:
    """Finalize merge/cleanup for a residue task lane."""
    if not task_id:
        return "Error: task_id required for finalize_merge"
    result = await bash_fn(_st_cmd(f"git finalize-task {shlex.quote(task_id)}", project_id))
    if "no_worktree" in result:
        return (
            f"{result}\n"
            "Task already appears closed: no worktree remains to finalize. "
            "Treat this as closure evidence unless other task context still shows a live lane."
        )
    if "task not found" in result.lower():
        return (
            f"{result}\n"
            "Hint: a cleanup_status `review:` candidate is not a direct finalize_merge target. "
            "Use cleanup_worktrees, get_context, query_sessions, or reconcile first."
        )
    return result


async def _handle_resolve_conflict(
    bash_fn: Callable[..., Awaitable[str]],
    task_id: str | None,
    project_id: str | None,
) -> str:
    """Reopen residue conflict work and hand it to the canonical execution path."""
    if not task_id:
        return "Error: task_id required for resolve_conflict"
    return await bash_fn(_st_cmd(f"git resolve-conflict {shlex.quote(task_id)}", project_id))
