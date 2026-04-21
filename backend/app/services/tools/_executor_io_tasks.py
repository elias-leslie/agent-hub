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
_DEFAULT_COMPLEXITY = "STANDARD"
_DEFAULT_SUBTASK_STEP = "Complete this subtask."
_PROJECT_ID_REQUIRED = "Error: project_id required for {action}"
_TASK_ID_REQUIRED = "Error: task_id required for {action}"
_STATUS_RUNNING = "running"
_STATUS_ACTIVE = "active"
_PERMISSION_TIER_OFF = "off"
_PERMISSION_MODE_AUTO = "auto-exec"
_PERMISSION_MODE_MANUAL = "manual"
_CLEANUP_REVIEW_MARKER = " review:"
_CLEANUP_CONFLICTS_MARKER = " conflicts:"
_CLEANUP_FINALIZE_MARKER = " finalize:"
_NO_CHECKPOINT = "no_checkpoint"
_TASK_NOT_FOUND = "task not found"
_MERGED_STATUS = "merged"
_PLAN_CONTEXT_LIST_FIELDS = ("files_to_modify", "files_to_create", "risks")
_PLAN_ROOT_LIST_FIELDS = ("done_when", "constraints")


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
    return [text for item in value if (text := _clean_text(item))]


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


def _copy_nonempty_dict(value: object) -> dict[str, object] | None:
    """Return shallow dict copy when input is a non-empty dict."""
    if not isinstance(value, dict) or not value:
        return None
    copied = {key: item for key, item in value.items() if isinstance(key, str)}
    return copied or None


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
        rows.extend(
            {
                "project_id": owner_project_id,
                "external_id": task_id,
                "workstream_status": status.strip(),
            }
            for status in statuses.split(",")
            if status.strip()
        )
    return rows


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
    if spec := _copy_nonempty_dict(step.get("spec")):
        normalized["spec"] = spec
    return normalized


def _normalize_context(context: dict[str, object] | None) -> dict[str, object] | None:
    """Keep only explicit plan-context mapping supported by SummitFlow."""
    if not context:
        return None

    normalized: dict[str, object] = {}
    for field in _PLAN_CONTEXT_LIST_FIELDS:
        if values := _normalize_string_list(context.get(field)):
            normalized[field] = values
    if references := _normalize_references(context.get("references")):
        normalized["references"] = references
    if second_opinion := _copy_nonempty_dict(context.get("second_opinion")):
        normalized["second_opinion"] = second_opinion
    return normalized or None


def _normalize_subtask_steps(description: str, raw_steps: object) -> list[str | dict[str, object]]:
    """Return normalized steps, defaulting to subtask description."""
    if isinstance(raw_steps, list):
        steps = [step for step in (_normalize_step(step) for step in raw_steps) if step]
        if steps:
            return steps
    return [description.strip() or _DEFAULT_SUBTASK_STEP]


def _normalize_subtask(subtask: object) -> dict[str, object] | None:
    """Normalize one subtask to execution-ready SummitFlow schema."""
    if not isinstance(subtask, dict):
        return None

    subtask_id = _clean_text(subtask.get("id"))
    description = _clean_text(subtask.get("description"))
    if not subtask_id or not description:
        return None

    normalized: dict[str, object] = {"id": subtask_id, "description": description}
    for key in ("phase", "subtask_type"):
        if value := _clean_text(subtask.get(key)):
            normalized[key] = value
    if depends_on := _normalize_string_list(subtask.get("depends_on")):
        normalized["depends_on"] = depends_on
    normalized["steps"] = _normalize_subtask_steps(description, subtask.get("steps"))
    return normalized


def _normalize_subtask_plan(
    subtasks: list[dict[str, object]] | None,
) -> list[dict[str, object]] | None:
    """Ensure plan subtasks include at least one explicit step for execution readiness."""
    if not subtasks:
        return subtasks
    return [normalized for subtask in subtasks if (normalized := _normalize_subtask(subtask))]


def _split_labels(labels: str | None) -> list[str] | None:
    """Return comma-split label list when present."""
    return labels.split(",") if labels else None


def _base_plan(
    title: str,
    priority: int,
    task_type: str,
    complexity: str | None,
) -> dict[str, object]:
    """Return required plan fields."""
    return {
        "title": title,
        "task_type": task_type,
        "priority": priority,
        "complexity": complexity or _DEFAULT_COMPLEXITY,
        "autonomous": True,
    }


def _optional_plan_fields(
    description: str | None,
    done_when: list[str] | None,
    labels: str | None,
    objective: str | None,
    constraints: list[str] | None,
    spirit_anti: str | None,
    testing_strategy: str | None,
    context: dict[str, object] | None,
    subtasks: list[dict[str, object]] | None,
) -> dict[str, object]:
    """Return optional normalized plan fields."""
    fields: dict[str, object] = {}
    scalar_fields = {
        "description": description,
        "objective": _clean_text(objective),
        "spirit_anti": _clean_text(spirit_anti),
        "testing_strategy": _clean_text(testing_strategy),
    }
    fields.update({key: value for key, value in scalar_fields.items() if value})

    list_fields = {
        "done_when": done_when,
        "constraints": _normalize_string_list(constraints),
        "labels": _split_labels(labels),
        "subtasks": _normalize_subtask_plan(subtasks),
    }
    fields.update({key: value for key, value in list_fields.items() if value})

    if normalized_context := _normalize_context(context):
        fields["context"] = normalized_context
    return fields


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
    plan = _base_plan(title, priority, task_type, complexity)
    plan.update(
        _optional_plan_fields(
            description,
            done_when,
            labels,
            objective,
            constraints,
            spirit_anti,
            testing_strategy,
            context,
            subtasks,
        )
    )

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, prefix="st-plan-"
    ) as file_handle:
        json.dump(plan, file_handle)
        return file_handle.name


def _has_plan_payload(
    done_when: list[str] | None,
    complexity: str | None,
    objective: str | None,
    constraints: list[str] | None,
    spirit_anti: str | None,
    testing_strategy: str | None,
    context: dict[str, object] | None,
    subtasks: list[dict[str, object]] | None,
) -> bool:
    """Return whether create call needs plan-json path."""
    return any(
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
    )


def _basic_create_subcommand(
    title: str,
    description: str | None,
    priority: int,
    task_type: str,
    labels: str | None,
) -> str:
    """Return plain st create subcommand."""
    command = f"create {shlex.quote(title)} -t {shlex.quote(task_type)} -p {priority}"
    if description:
        command += f" -d {shlex.quote(description)}"
    if labels:
        command += f" -l {shlex.quote(labels)}"
    return command


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
    if _has_plan_payload(
        done_when,
        complexity,
        objective,
        constraints,
        spirit_anti,
        testing_strategy,
        context,
        subtasks,
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

    cmd = _st_cmd(
        _basic_create_subcommand(title, description, priority, task_type, labels),
        project_id,
    )
    logger.info("manage_tasks create: %s", cmd)
    return await bash_fn(cmd)


async def _ownership_workstream_rows(
    bash_fn: Callable[..., Awaitable[str]],
    project_id: str,
) -> list[dict[str, object]]:
    """Return live ownership rows when available."""
    try:
        ownership_output = await bash_fn(_st_cmd("sessions ownership", project_id))
    except Exception:
        return []
    return _ownership_rows_to_workstream_rows(ownership_output, project_id=project_id)


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

    if use_live_ownership and (workstream_rows := await _ownership_workstream_rows(bash_fn, project_id)):
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


def _running_task_warning(running: list[dict[str, str]], project_id: str | None) -> str | None:
    """Return warning text for already-running tasks."""
    if not running:
        return None
    project_label = f" in {project_id}" if project_id else ""
    ids = ", ".join(task.get("id", "?") for task in running[:5])
    return (
        f"WARNING: {len(running)} task(s) already running{project_label}: {ids}. "
        "Risk of merge conflicts."
    )


def _cleanup_finalize_warning(cleanup_status: str | None) -> str | None:
    """Return warning for merge-ready cleanup residue."""
    if cleanup_status and _CLEANUP_FINALIZE_MARKER in cleanup_status:
        return (
            "WARNING: merge-ready residue detected in cleanup status. "
            "Prefer finalize_merge, reconcile, or cleanup_checkpoints when convenient."
        )
    return None


async def _build_dispatch_warning(
    bash_fn: Callable[..., Awaitable[str]],
    project_id: str | None,
    cleanup_status: str | None = None,
) -> str:
    """Return warning string if tasks are already running, else empty string."""
    try:
        warnings: list[str] = []
        running_json = await bash_fn(_st_cmd(f"list --status {_STATUS_RUNNING} --json", project_id))
        running: list[dict[str, str]] = json.loads(running_json) if running_json.strip() else []
        if running_warning := _running_task_warning(running, project_id):
            warnings.append(running_warning)
        if project_id:
            current_cleanup_status = cleanup_status or await bash_fn(_st_cmd("cleanup status", project_id))
            if finalize_warning := _cleanup_finalize_warning(current_cleanup_status):
                warnings.append(finalize_warning)
        return "\n\n".join(warnings) + ("\n\n" if warnings else "")
    except Exception:
        return ""


async def _cleanup_dispatch_block_reason(
    bash_fn: Callable[..., Awaitable[str]],
    project_id: str | None,
    *,
    use_live_ownership: bool = True,
) -> tuple[str | None, str | None]:
    """Return blocking reason when cleanup residue should stop new dispatches."""
    if not project_id:
        return (None, None)
    try:
        cleanup_status = await bash_fn(_st_cmd("cleanup status", project_id))
    except Exception:
        return (None, None)

    has_blocking_residue = (
        _CLEANUP_CONFLICTS_MARKER in cleanup_status or _CLEANUP_REVIEW_MARKER in cleanup_status
    )
    if not has_blocking_residue:
        return None, cleanup_status

    filtered_items = await _filtered_cleanup_action_items(
        bash_fn,
        cleanup_status,
        project_id,
        use_live_ownership=use_live_ownership and _CLEANUP_REVIEW_MARKER in cleanup_status,
    )
    if not filtered_items:
        return None, cleanup_status

    actionable = build_actionable_cleanup_summary_from_items(filtered_items)
    return (
        "Dispatch blocked: unresolved cleanup residue detected in cleanup status. "
        "Use finalize_merge, reconcile, or cleanup_checkpoints before dispatching more work."
        f"\n\n{actionable}"
    ), cleanup_status


def _active_session_block_message(
    task_id: str,
    active_sessions: list[object],
    freshest_idle: float,
    task_detail: str,
) -> str:
    """Return block message for already-active same-task session."""
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
    """Return block message for running task with or without recent activity."""
    if has_recent_activity:
        return (
            f"Dispatch blocked for {task_id}: task is already running and shows recent "
            "autonomous activity. Wait or inspect the current lane instead of redispatching."
        )
    return (
        f"Dispatch blocked for {task_id}: task is already running{task_detail} without fresh "
        "session evidence. Inspect or reconcile the current lane before dispatching again."
    )


async def _active_session_idle_minutes(active_sessions: list[object]) -> float:
    """Return freshest idle minutes across active sessions."""
    now = datetime.now(UTC)
    return min(
        idle_minutes_from_timestamps(
            created_at=getattr(session, "created_at", None),
            updated_at=getattr(session, "updated_at", None),
            workstream_updated_at=getattr(session, "workstream_updated_at", None),
            now=now,
        )
        for session in active_sessions
    )


async def _live_dispatch_block_reason(
    bash_fn: Callable[..., Awaitable[str]],
    task_id: str,
    project_id: str | None,
) -> str | None:
    """Return blocking reason when same-task live state says wait or reconcile."""
    if not project_id or not task_id.startswith(_CANONICAL_TASK_ID_PREFIX):
        return None

    from ._executor_io_lanes import (
        _get_task_status,
        _has_recent_execution_activity,
        _load_task_lane_sessions,
    )

    task_status = await _get_task_status(bash_fn, task_id, project_id)
    sessions = await _load_task_lane_sessions(task_id)
    active_sessions = [session for session in sessions if getattr(session, "status", None) == _STATUS_ACTIVE]
    task_detail = f" (task={task_status})" if task_status else ""

    if active_sessions:
        freshest_idle = await _active_session_idle_minutes(active_sessions)
        return _active_session_block_message(task_id, active_sessions, freshest_idle, task_detail)
    if task_status == _STATUS_RUNNING:
        has_recent = await _has_recent_execution_activity(bash_fn, task_id, project_id)
        return _running_task_block_message(task_id, task_detail, has_recent)
    return None


def _permission_access_label(permission: Any) -> str:
    """Return permission label used in dispatch-block message."""
    mode = _PERMISSION_MODE_AUTO if permission.auto_exec_enabled else _PERMISSION_MODE_MANUAL
    return f"{permission.permission_tier}/{mode}"


def _permission_detail(permission: Any) -> str:
    """Return reason detail for blocked execution permission."""
    if permission.permission_tier == _PERMISSION_TIER_OFF:
        return "project access is off"
    if not permission.auto_exec_enabled:
        return "project is observe-only for autonomous execution"
    if not permission.in_time_window:
        return "project is outside its execution window"
    return f"execution permission check returned {permission.reason}"


async def _dispatch_permission_block_reason(project_id: str | None) -> str | None:
    """Return blocking reason when project access disallows autonomous dispatch."""
    if not project_id:
        return None

    from app.db import async_session

    async with async_session() as db:
        permission = await check_execution_permission(db, project_id)

    valid_payload = all(
        (
            isinstance(permission.allowed, bool),
            isinstance(permission.permission_tier, str),
            isinstance(permission.auto_exec_enabled, bool),
            isinstance(permission.in_time_window, bool),
        )
    )
    if not valid_payload:
        logger.debug(
            "Skipping dispatch permission gate for %s due to invalid permission payload: %r",
            project_id,
            permission,
        )
        return None
    if permission.allowed:
        return None

    return (
        f"Dispatch blocked: project {project_id} is {_permission_access_label(permission)}; "
        f"{_permission_detail(permission)}. "
        "Read/manual projects are observe-only during heartbeat unless access changes."
    )


async def _handle_dispatch(
    bash_fn: Callable[..., Awaitable[str]],
    task_id: str,
    project_id: str | None,
) -> str:
    """Dispatch task via autocode, prefixed with any running-task warning."""
    if permission_block := await _dispatch_permission_block_reason(project_id):
        return permission_block
    cleanup_block, cleanup_status = await _cleanup_dispatch_block_reason(
        bash_fn,
        project_id,
        use_live_ownership=False,
    )
    if cleanup_block:
        return cleanup_block
    if live_block := await _live_dispatch_block_reason(bash_fn, task_id, project_id):
        return live_block
    warning = await _build_dispatch_warning(bash_fn, project_id, cleanup_status=cleanup_status)
    result = await bash_fn(_st_cmd(f"autocode {shlex.quote(task_id)}", project_id))
    return warning + result


def _require_project_id(project_id: str | None, action: str) -> str | None:
    """Return error for actions that require project id."""
    if project_id:
        return None
    return _PROJECT_ID_REQUIRED.format(action=action)


def _require_task_id(task_id: str | None, action: str) -> str | None:
    """Return error for actions that require task id."""
    if task_id:
        return None
    return _TASK_ID_REQUIRED.format(action=action)


async def _handle_cleanup_status(
    bash_fn: Callable[..., Awaitable[str]], project_id: str | None,
) -> str:
    """Return canonical cleanup status for concrete project."""
    if error := _require_project_id(project_id, "cleanup_status"):
        return error
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


def _cleanup_header_state(cleanup_status: str) -> tuple[bool, bool]:
    """Return whether cleanup header reports active checkpoints or branch residue."""
    header = cleanup_status.splitlines()[0] if cleanup_status else ""
    has_active_checkpoints = "checkpoints=0" not in header
    has_branch_residue = "orphan=0" not in header or "prunable=0" not in header
    return has_active_checkpoints, has_branch_residue


async def _handle_cleanup_checkpoints(
    bash_fn: Callable[..., Awaitable[str]], project_id: str | None,
) -> str:
    """Safely clean checkpoint residue for concrete project."""
    if error := _require_project_id(project_id, "cleanup_checkpoints"):
        return error
    cleanup_status = await bash_fn(_st_cmd("cleanup status", project_id))
    actionable = build_actionable_cleanup_summary(cleanup_status)
    has_active_checkpoints, has_branch_residue = _cleanup_header_state(cleanup_status)
    if not has_active_checkpoints and not has_branch_residue:
        return f"{cleanup_status}\n\nCleanup complete for {project_id}."
    result = await bash_fn(_st_cmd("cleanup checkpoints --auto", project_id))
    return f"{result}\n\n{actionable}" if actionable else result


async def _handle_cleanup_salvage_orphan(
    bash_fn: Callable[..., Awaitable[str]], task_id: str | None, project_id: str | None,
) -> str:
    """Recover missing-task salvage candidate into normal task checkpoint."""
    if error := _require_task_id(task_id, "salvage_orphan"):
        return error
    if error := _require_project_id(project_id, "salvage_orphan"):
        return error
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
    """Publish one project's coherent repo state via canonical smart-sync path."""
    if error := _require_project_id(project_id, "smart_sync"):
        return error
    return await bash_fn(_st_cmd("smart-sync", project_id))


def _parse_finalize_result(result: str) -> dict[str, Any] | None:
    """Return finalize result JSON dict when command emitted one."""
    try:
        payload = json.loads(result)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _finalize_no_checkpoint_message(result: str) -> str:
    """Return no-checkpoint finalize guidance."""
    return (
        f"{result}\n"
        "Task already appears closed: no checkpoint remains to finalize. "
        "Treat this as closure evidence unless other task context still shows a live session."
    )


def _finalize_task_not_found_message(result: str) -> str:
    """Return task-not-found finalize guidance."""
    return (
        f"{result}\n"
        "Hint: a cleanup_status `review:` candidate is not a direct finalize_merge target. "
        "Use cleanup_checkpoints, get_context, query_sessions, or reconcile first."
    )


async def _handle_finalize_merge(
    bash_fn: Callable[..., Awaitable[str]],
    task_id: str | None,
    project_id: str | None,
) -> str:
    """Finalize merge/cleanup for residue task checkpoint."""
    if error := _require_task_id(task_id, "finalize_merge"):
        return error
    result = await bash_fn(_st_cmd(f"git finalize-task {shlex.quote(task_id)}", project_id))
    parsed = _parse_finalize_result(result)
    if _NO_CHECKPOINT in result:
        return _finalize_no_checkpoint_message(result)
    if _TASK_NOT_FOUND in result.lower():
        return _finalize_task_not_found_message(result)
    if parsed and parsed.get("status") == _MERGED_STATUS:
        from ._executor_io_lanes import _cleanup_explicit_lane

        cleanup_result = await _cleanup_explicit_lane(bash_fn, task_id, project_id)
        return f"{result}\nCheckpoint cleanup: {cleanup_result}"
    return result


async def _handle_resolve_conflict(
    bash_fn: Callable[..., Awaitable[str]],
    task_id: str | None,
    project_id: str | None,
) -> str:
    """Reopen residue conflict work and hand it to canonical execution path."""
    if error := _require_task_id(task_id, "resolve_conflict"):
        return error
    return await bash_fn(_st_cmd(f"git resolve-conflict {shlex.quote(task_id)}", project_id))


async def _handle_done(
    bash_fn: Callable[..., Awaitable[str]],
    task_id: str | None,
) -> str:
    """Mark task complete using admin path required for autonomous closeout."""
    if error := _require_task_id(task_id, "done"):
        return error
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
