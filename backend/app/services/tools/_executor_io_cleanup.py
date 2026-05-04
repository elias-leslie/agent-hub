"""Cleanup and residue helpers for DirectToolExecutor task actions."""

from __future__ import annotations

import shlex
from collections.abc import Awaitable, Callable

from app.services.cleanup_summary import (
    build_actionable_cleanup_summary,
    build_actionable_cleanup_summary_from_items,
    build_filtered_reconciled_cleanup_note,
    extract_cleanup_action_items,
    filter_reconciled_cleanup_items,
)
from app.services.tools._tool_constants import st_cmd as _st_cmd

_CANONICAL_TASK_ID_PREFIX = "task-"
_PROJECT_ID_REQUIRED = "Error: project_id required for {action}"
_TASK_ID_REQUIRED = "Error: task_id required for {action}"
_CLEANUP_REVIEW_MARKER = " review:"
_CLEANUP_CONFLICTS_MARKER = " conflicts:"
_CLEANUP_FINALIZE_MARKER = " finalize:"


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


def _cleanup_finalize_warning(cleanup_status: str | None) -> str | None:
    """Return warning for merge-ready cleanup residue."""
    if cleanup_status and _CLEANUP_FINALIZE_MARKER in cleanup_status:
        return (
            "WARNING: merge-ready residue detected in cleanup status. "
            "Use reconcile or cleanup_checkpoints before dispatching more work."
        )
    return None


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
        "Use reconcile or cleanup_checkpoints before dispatching more work."
        f"\n\n{actionable}"
    ), cleanup_status


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


async def _handle_resolve_conflict(
    bash_fn: Callable[..., Awaitable[str]],
    task_id: str | None,
    project_id: str | None,
) -> str:
    """Reopen residue conflict work and hand it to canonical execution path."""
    if error := _require_task_id(task_id, "resolve_conflict"):
        return error
    return await bash_fn(_st_cmd(f"git resolve-conflict {shlex.quote(task_id)}", project_id))


__all__ = [
    "_cleanup_dispatch_block_reason",
    "_cleanup_finalize_warning",
    "_handle_cleanup_all_safe",
    "_handle_cleanup_checkpoints",
    "_handle_cleanup_salvage_orphan",
    "_handle_cleanup_status",
    "_handle_resolve_conflict",
]
