"""Task creation, dispatch, and cleanup helpers for DirectToolExecutor."""

from __future__ import annotations

import json
import logging
import shlex
import tempfile
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from app.services.cleanup_summary import (
    build_actionable_cleanup_summary,
    build_actionable_cleanup_summary_from_items,
    build_filtered_reconciled_cleanup_note,
    extract_cleanup_action_items,
    filter_reconciled_cleanup_items,
)
from app.services.ownership_lanes import (
    STALE_WORKSTREAM_IDLE_MINUTES,
    idle_minutes_from_timestamps,
)
from app.services.project_permission_service import check_execution_permission
from app.services.tools._tool_constants import st_cmd as _st_cmd

logger = logging.getLogger(__name__)
_CANONICAL_TASK_ID_PREFIX = "task-"
_PLAN_CONTEXT_LIST_FIELDS = ("files_to_modify", "files_to_create", "risks")
_PLAN_ROOT_LIST_FIELDS = ("done_when", "constraints")


def _ownership_rows_to_workstream_rows(
    ownership_output: str,
    *,
    project_id: str,
) -> list[dict[str, object]]:
    """Convert `st sessions ownership` text output into minimal workstream rows."""
    rows: list[dict[str, object]] = []
    for raw_line in ownership_output.splitlines():
        line = raw_line.strip()
        if not line.startswith("- "):
            continue
        parts = [part.strip() for part in line[2:].split("|")]
        if len(parts) < 4:
            continue
        owner_project_id, task_id, _idle, statuses = parts[:4]
        if owner_project_id != project_id or not task_id.startswith(_CANONICAL_TASK_ID_PREFIX):
            continue
        for status in (status.strip() for status in statuses.split(",")):
            if status:
                rows.append(
                    {
                        "project_id": owner_project_id,
                        "external_id": task_id,
                        "workstream_status": status,
                    }
                )
    return rows


def _clean_text(value: object) -> str | None:
    """Return stripped text or None for empty/non-string-compatible values."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _normalize_string_list(value: object) -> list[str]:
    """Normalize a list of strings, dropping empty entries."""
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        text = _clean_text(item)
        if text:
            normalized.append(text)
    return normalized


def _normalize_references(value: object) -> list[dict[str, str]]:
    """Normalize plan context references to {title,url} objects."""
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        title = _clean_text(item.get("title"))
        url = _clean_text(item.get("url"))
        if title and url:
            normalized.append({"title": title, "url": url})
    return normalized


def _normalize_step(step: object) -> str | dict[str, object] | None:
    """Normalize a plan step to the SummitFlow schema shape."""
    if isinstance(step, str):
        return _clean_text(step)
    if not isinstance(step, dict):
        return None

    description = _clean_text(step.get("description"))
    if not description:
        return None

    normalized: dict[str, object] = {"description": description}
    spec = step.get("spec")
    if isinstance(spec, dict) and spec:
        normalized["spec"] = dict(spec)
    return normalized


def _normalize_context(context: dict[str, object] | None) -> dict[str, object] | None:
    """Keep only the explicit plan-context mapping supported by SummitFlow."""
    if not context:
        return None

    normalized: dict[str, object] = {}
    for field in _PLAN_CONTEXT_LIST_FIELDS:
        values = _normalize_string_list(context.get(field))
        if values:
            normalized[field] = values

    references = _normalize_references(context.get("references"))
    if references:
        normalized["references"] = references

    second_opinion = context.get("second_opinion")
    if isinstance(second_opinion, dict) and second_opinion:
        normalized["second_opinion"] = dict(second_opinion)

    return normalized or None


def _normalize_subtask_plan(
    subtasks: list[dict[str, object]] | None,
) -> list[dict[str, object]] | None:
    """Ensure plan subtasks include at least one explicit step for execution readiness."""
    if not subtasks:
        return subtasks

    normalized: list[dict[str, object]] = []
    for subtask in subtasks:
        if not isinstance(subtask, dict):
            continue
        subtask_id = _clean_text(subtask.get("id"))
        description = _clean_text(subtask.get("description"))
        if not subtask_id or not description:
            continue

        normalized_subtask: dict[str, object] = {
            "id": subtask_id,
            "description": description,
        }
        if phase := _clean_text(subtask.get("phase")):
            normalized_subtask["phase"] = phase
        if subtask_type := _clean_text(subtask.get("subtask_type")):
            normalized_subtask["subtask_type"] = subtask_type
        if depends_on := _normalize_string_list(subtask.get("depends_on")):
            normalized_subtask["depends_on"] = depends_on

        raw_steps = subtask.get("steps")
        normalized_steps = (
            [step for step in (_normalize_step(step) for step in raw_steps) if step]
            if isinstance(raw_steps, list)
            else []
        )
        if normalized_steps:
            normalized_subtask["steps"] = normalized_steps
        else:
            step_text = description.strip()
            normalized_subtask["steps"] = [step_text or "Complete this subtask."]
        normalized.append(normalized_subtask)
    return normalized


def _build_plan_json(
    title: str,
    description: str | None,
    priority: int,
    task_type: str,
    done_when: list[str] | None,
    labels: str | None,
    complexity: str | None,
    objective: str | None = None,
    constraints: list[str] | None = None,
    spirit_anti: str | None = None,
    testing_strategy: str | None = None,
    context: dict[str, object] | None = None,
    subtasks: list[dict[str, object]] | None = None,
) -> str:
    """Write a plan JSON to a temp file and return its path."""
    plan: dict[str, object] = {
        "title": title,
        "task_type": task_type,
        "priority": priority,
        "complexity": complexity or "STANDARD",
        "autonomous": True,
    }
    if description:
        plan["description"] = description
    if done_when:
        plan["done_when"] = done_when
    if labels:
        plan["labels"] = labels.split(",")
    if objective_text := _clean_text(objective):
        plan["objective"] = objective_text
    if constraint_list := _normalize_string_list(constraints):
        plan["constraints"] = constraint_list
    if anti_text := _clean_text(spirit_anti):
        plan["spirit_anti"] = anti_text
    if testing_text := _clean_text(testing_strategy):
        plan["testing_strategy"] = testing_text
    if normalized_context := _normalize_context(context):
        plan["context"] = normalized_context
    if subtasks:
        plan["subtasks"] = _normalize_subtask_plan(subtasks)

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
    objective: str | None = None,
    constraints: list[str] | None = None,
    spirit_anti: str | None = None,
    testing_strategy: str | None = None,
    context: dict[str, object] | None = None,
    subtasks: list[dict[str, object]] | None = None,
) -> str:
    """Handle task creation — plan-based or basic."""
    if any(
        (
            done_when,
            complexity,
            objective,
            constraints,
            spirit_anti,
            testing_strategy,
            context,
            subtasks,
        )
    ):
        tmpfile = _build_plan_json(
            title,
            description,
            priority,
            task_type,
            done_when,
            labels,
            complexity,
            objective=objective,
            constraints=constraints,
            spirit_anti=spirit_anti,
            testing_strategy=testing_strategy,
            context=context,
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


async def _filtered_cleanup_action_items(
    bash_fn: Callable[..., Awaitable[str]],
    cleanup_status: str,
    project_id: str,
    *,
    use_live_ownership: bool = False,
) -> list:
    """Return cleanup items after dropping reconciled authoritative/superseded residue."""
    items = extract_cleanup_action_items(cleanup_status)
    if not items:
        return []

    if use_live_ownership:
        try:
            ownership_output = await bash_fn(_st_cmd("sessions ownership", project_id))
        except Exception:
            ownership_output = ""

        workstream_rows = _ownership_rows_to_workstream_rows(
            ownership_output,
            project_id=project_id,
        )
        if workstream_rows:
            return filter_reconciled_cleanup_items(items, workstream_rows)

    from app.workflows._heartbeat_data import _query_recent_workstream_sessions

    fallback_rows = await _query_recent_workstream_sessions(project_id)
    if not fallback_rows:
        return items
    return filter_reconciled_cleanup_items(items, fallback_rows)


async def _build_filtered_actionable_cleanup_summary(
    bash_fn: Callable[..., Awaitable[str]],
    cleanup_status: str,
    project_id: str,
) -> str:
    """Build actionable cleanup summary with reconciled residue filtered out."""
    raw_items = extract_cleanup_action_items(cleanup_status)
    filtered_items = await _filtered_cleanup_action_items(bash_fn, cleanup_status, project_id)
    return (
        build_actionable_cleanup_summary_from_items(filtered_items)
        or build_filtered_reconciled_cleanup_note(raw_items, filtered_items)
    )


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
                    "Prefer finalize_merge, reconcile, or cleanup_checkpoints when convenient."
                )
        return "\n\n".join(warnings) + ("\n\n" if warnings else "")
    except Exception:
        return ""  # Never block dispatch on warning failure


async def _cleanup_dispatch_block_reason(
    bash_fn: Callable[..., Awaitable[str]],
    project_id: str | None,
    *,
    use_live_ownership: bool = True,
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
        filtered_items = await _filtered_cleanup_action_items(
            bash_fn,
            cleanup_status,
            project_id,
            use_live_ownership=use_live_ownership and " review:" in cleanup_status,
        )
        actionable = build_actionable_cleanup_summary_from_items(filtered_items)
        if filtered_items:
            return (
                "Dispatch blocked: unresolved cleanup residue detected in cleanup status. "
                "Use finalize_merge, reconcile, or cleanup_checkpoints before dispatching more work."
                f"\n\n{actionable}"
            ), cleanup_status
    return None, cleanup_status


def _active_session_block_message(
    task_id: str,
    active_sessions: list[object],
    freshest_idle: float,
    task_detail: str,
) -> str:
    """Return a block message for an already-active same-task session."""
    count = len(active_sessions)
    if freshest_idle < STALE_WORKSTREAM_IDLE_MINUTES:
        return (
            f"Dispatch blocked for {task_id}: same task already has {count} "
            f"active session(s){task_detail} with fresh progress ({freshest_idle}m idle). "
            "Wait or monitor the current lane instead of redispatching."
        )
    return (
        f"Dispatch blocked for {task_id}: same task still has {count} "
        f"stale active session(s){task_detail} ({freshest_idle}m idle). "
        "Inspect or reconcile the current lane before dispatching again."
    )


def _running_task_block_message(task_id: str, task_detail: str, has_recent_activity: bool) -> str:
    """Return a block message for a running task with or without recent activity."""
    if has_recent_activity:
        return (
            f"Dispatch blocked for {task_id}: task is already running and shows recent "
            "autonomous activity. Wait or inspect the current lane instead of redispatching."
        )
    return (
        f"Dispatch blocked for {task_id}: task is already running{task_detail} without fresh "
        "session evidence. Inspect or reconcile the current lane before dispatching again."
    )


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
    active_sessions = [s for s in sessions if getattr(s, "status", None) == "active"]
    task_detail = f" (task={task_status})" if task_status else ""

    if active_sessions:
        now = datetime.now(UTC)
        freshest_idle = min(
            idle_minutes_from_timestamps(
                created_at=getattr(s, "created_at", None),
                updated_at=getattr(s, "updated_at", None),
                workstream_updated_at=getattr(s, "workstream_updated_at", None),
                now=now,
            )
            for s in active_sessions
        )
        return _active_session_block_message(task_id, active_sessions, freshest_idle, task_detail)

    if task_status == "running":
        has_recent = await _has_recent_execution_activity(bash_fn, task_id, project_id)
        return _running_task_block_message(task_id, task_detail, has_recent)

    return None


async def _dispatch_permission_block_reason(project_id: str | None) -> str | None:
    """Return a blocking reason when project access disallows autonomous dispatch."""
    if not project_id:
        return None

    from app.db import async_session

    async with async_session() as db:
        permission = await check_execution_permission(db, project_id)

    if not (
        isinstance(permission.allowed, bool)
        and isinstance(permission.permission_tier, str)
        and isinstance(permission.auto_exec_enabled, bool)
        and isinstance(permission.in_time_window, bool)
    ):
        logger.debug(
            "Skipping dispatch permission gate for %s due to invalid permission payload: %r",
            project_id,
            permission,
        )
        return None

    if permission.allowed:
        return None

    access_label = (
        f"{permission.permission_tier}/auto-exec"
        if permission.auto_exec_enabled
        else f"{permission.permission_tier}/manual"
    )
    if permission.permission_tier == "off":
        detail = "project access is off"
    elif not permission.auto_exec_enabled:
        detail = "project is observe-only for autonomous execution"
    elif not permission.in_time_window:
        detail = "project is outside its execution window"
    else:
        detail = f"execution permission check returned {permission.reason}"
    return (
        f"Dispatch blocked: project {project_id} is {access_label}; {detail}. "
        "Read/manual projects are observe-only during heartbeat unless access changes."
    )


async def _handle_dispatch(
    bash_fn: Callable[..., Awaitable[str]],
    task_id: str,
    project_id: str | None,
) -> str:
    """Dispatch a task via autocode, prefixed with any running-task warning."""
    permission_block = await _dispatch_permission_block_reason(project_id)
    if permission_block:
        return permission_block
    block_reason, cleanup_status = await _cleanup_dispatch_block_reason(
        bash_fn,
        project_id,
        use_live_ownership=False,
    )
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
    if not actionable:
        return cleanup_status

    filtered_actionable = await _build_filtered_actionable_cleanup_summary(
        bash_fn,
        cleanup_status,
        project_id,
    )
    return f"{cleanup_status}\n\n{filtered_actionable}" if filtered_actionable else cleanup_status


async def _handle_cleanup_checkpoints(
    bash_fn: Callable[..., Awaitable[str]], project_id: str | None,
) -> str:
    """Safely clean checkpoint residue for a concrete project."""
    if not project_id:
        return 'Error: project_id required for cleanup_checkpoints'
    cleanup_status = await bash_fn(_st_cmd("cleanup status", project_id))
    actionable = build_actionable_cleanup_summary(cleanup_status)
    header = cleanup_status.splitlines()[0] if cleanup_status else ""
    has_active_checkpoints = "checkpoints=0" not in header
    has_branch_residue = "orphan=0" not in header or "prunable=0" not in header
    if not has_active_checkpoints and not has_branch_residue:
        return f"{cleanup_status}\n\nCleanup complete for {project_id}."
    result = await bash_fn(_st_cmd("cleanup checkpoints --auto", project_id))
    return f"{result}\n\n{actionable}" if actionable else result


async def _handle_cleanup_salvage_orphan(
    bash_fn: Callable[..., Awaitable[str]], task_id: str | None, project_id: str | None,
) -> str:
    """Recover a missing-task salvage candidate into a normal task checkpoint."""
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
    cleanup_result = await bash_fn("st cleanup checkpoints --auto --all")
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
    return await bash_fn(_st_cmd("smart-sync", project_id))


async def _handle_finalize_merge(
    bash_fn: Callable[..., Awaitable[str]],
    task_id: str | None,
    project_id: str | None,
) -> str:
    """Finalize merge/cleanup for a residue task checkpoint."""
    if not task_id:
        return "Error: task_id required for finalize_merge"
    result = await bash_fn(_st_cmd(f"git finalize-task {shlex.quote(task_id)}", project_id))
    parsed: dict[str, Any] | None = None
    try:
        maybe_json = json.loads(result)
        if isinstance(maybe_json, dict):
            parsed = maybe_json
    except json.JSONDecodeError:
        parsed = None
    if "no_checkpoint" in result:
        return (
            f"{result}\n"
            "Task already appears closed: no checkpoint remains to finalize. "
            "Treat this as closure evidence unless other task context still shows a live session."
        )
    if "task not found" in result.lower():
        return (
            f"{result}\n"
            "Hint: a cleanup_status `review:` candidate is not a direct finalize_merge target. "
            "Use cleanup_checkpoints, get_context, query_sessions, or reconcile first."
        )
    if parsed and parsed.get("status") == "merged":
        from ._executor_io_lanes import _cleanup_explicit_lane

        cleanup_result = await _cleanup_explicit_lane(bash_fn, task_id, project_id)
        return f"{result}\nCheckpoint cleanup: {cleanup_result}"
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


async def _handle_done(
    bash_fn: Callable[..., Awaitable[str]],
    task_id: str | None,
) -> str:
    """Mark a task complete using the admin path required for autonomous closeout."""
    if not task_id:
        return "Error: task_id required for done"
    return await bash_fn(f"st complete {shlex.quote(task_id)} --admin")


__all__ = [
    "_handle_cleanup_all_safe",
    "_handle_cleanup_checkpoints",
    "_handle_cleanup_salvage_orphan",
    "_handle_cleanup_status",
    "_handle_create",
    "_handle_dispatch",
    "_handle_done",
    "_handle_finalize_merge",
    "_handle_resolve_conflict",
    "_handle_smart_sync",
]
