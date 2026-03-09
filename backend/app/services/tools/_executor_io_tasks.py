"""Task creation, dispatch, and cleanup helpers for DirectToolExecutor."""

from __future__ import annotations

import json
import logging
import shlex
import tempfile
from collections.abc import Awaitable, Callable

from app.services.cleanup_summary import build_actionable_cleanup_summary

logger = logging.getLogger(__name__)


def _st_cmd(subcommand: str, project_id: str | None = None) -> str:
    """Build st CLI command with -P flag in correct position (before subcommand)."""
    if project_id:
        return f"st -P {shlex.quote(project_id)} {subcommand}"
    return f"st {subcommand}"


def _build_plan_json(
    title: str,
    objective: str | None,
    description: str | None,
    spirit_anti: str | None,
    done_when: list[str] | None,
    labels: str | None,
    complexity: str | None,
    subtasks: list[dict[str, object]] | None = None,
) -> str:
    """Write a plan JSON to a temp file and return its path."""
    plan: dict[str, object] = {
        "title": title,
        "objective": objective or title,
        "complexity": complexity or "STANDARD",
        "autonomous": True,
    }
    if description:
        plan["description"] = description
    if spirit_anti:
        plan["spirit_anti"] = spirit_anti
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
    objective: str | None,
    spirit_anti: str | None,
    done_when: list[str] | None,
    complexity: str | None,
    subtasks: list[dict[str, object]] | None = None,
) -> str:
    """Handle task creation — plan-based or basic."""
    if objective or done_when or subtasks:
        tmpfile = _build_plan_json(
            title, objective, description, spirit_anti, done_when, labels, complexity,
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
            if " finalize:" in cleanup_status or " conflicts:" in cleanup_status:
                warnings.append(
                    "WARNING: unresolved merge/conflict residue detected in cleanup status. "
                    "Prefer finalize_merge or reconcile before dispatching more low-confidence work."
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
    if " finalize:" in cleanup_status or " conflicts:" in cleanup_status or " review:" in cleanup_status:
        return (
            "Dispatch blocked: unresolved cleanup residue detected in cleanup status. "
            "Use finalize_merge, reconcile, or cleanup_worktrees before dispatching more work."
        ), cleanup_status
    return None, cleanup_status


async def _handle_dispatch(
    bash_fn: Callable[..., Awaitable[str]],
    task_id: str,
    project_id: str | None,
) -> str:
    """Dispatch a task via autocode, prefixed with any running-task warning."""
    block_reason, cleanup_status = await _cleanup_dispatch_block_reason(bash_fn, project_id)
    if block_reason:
        return block_reason
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
    has_active_worktrees = " worktrees:0 " not in cleanup_status
    if not has_active_worktrees:
        if actionable:
            return (
                f"{cleanup_status}\n\n{actionable}\n\n"
                "No active worktrees remain. Do not call cleanup_worktrees again this heartbeat "
                "unless cleanup_status changes. Use reconcile/get_context for actionable residue."
            )
        return (
            f"{cleanup_status}\n\n"
            "No active worktrees remain. Do not call cleanup_worktrees again this heartbeat "
            "unless cleanup_status changes."
        )
    return await bash_fn(_st_cmd("cleanup worktrees --auto", project_id))


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
