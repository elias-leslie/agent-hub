"""Specialist dispatch logic — validation, overlap checks, and lane preparation.

Extracted from _executor_consultation.py to keep each module under 350 lines.
"""

from __future__ import annotations

import logging
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_SPECIALIST_AGENT_SLUGS = frozenset({"refactor", "debugger"})
_CODING_TASK_KEYWORDS = (
    "code", "coding", "bug", "fix", "refactor", "implement", "test",
    "build", "lint", "compile", "typescript", "python", "sql",
    "frontend", "backend", "api", "file",
)
_TASK_ID_RE = re.compile(r"(?im)^\s*Task(?:[- ]ID)?:\s*(task-[a-z0-9]+)\s*$")
_MODE_RE = re.compile(r"(?im)^\s*Mode:\s*(task|campaign)\s*$")
_BRANCH_RE = re.compile(r"(?im)^\s*(?:\+\s+)?([^\s]+)\s+\[task\]\s*$")
_SHARED_PLUMBING_MARKERS = (
    "/alembic/", "/migrations/", "/schema", "/schemas/", "/contract",
    "/contracts/", "/routing", "/routes/", "/config", "/build",
    "/exports", "/index.", "/utils/",
)


@dataclass(frozen=True)
class SpecialistDispatchRequest:
    mode: str | None
    task_id: str | None


@dataclass(frozen=True)
class SpecialistDispatchPlan:
    event_type: str
    current_branch: str | None = None
    working_dir: str | None = None


def _is_wake_dispatch_specialist_session(session: object) -> bool:
    request_source = getattr(session, "request_source", None)
    return isinstance(request_source, str) and request_source.startswith("persona_wake:dispatch")


def _is_shared_plumbing_path(path: str) -> bool:
    lowered = path.lower()
    return any(marker in lowered for marker in _SHARED_PLUMBING_MARKERS)


def _looks_like_coding_task(task: str) -> bool:
    return any(keyword in task.lower() for keyword in _CODING_TASK_KEYWORDS)


def dispatch_result_text(agent_slug: str, is_coding_agent: bool, task: str) -> str:
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


def parse_specialist_dispatch_request(task: str) -> SpecialistDispatchRequest:
    """Extract explicit specialist mode and optional task id from a dispatch prompt."""
    mode_match = _MODE_RE.search(task)
    task_match = _TASK_ID_RE.search(task)
    return SpecialistDispatchRequest(
        mode=mode_match.group(1).lower() if mode_match else None,
        task_id=task_match.group(1).lower() if task_match else None,
    )


# --- overlap-check sub-helpers ---


def _check_duplicate_campaign(
    project_id: str, agent_slug: str, specialists: list[object],
) -> str | None:
    duplicate = next(
        (
            s for s in specialists
            if getattr(s, "agent_slug", None) == agent_slug
            and getattr(s, "request_source", None) == "persona_wake:dispatch_campaign"
        ),
        None,
    )
    if duplicate is None:
        return None
        return (
            f"Dispatch blocked for {project_id}: {agent_slug} already has an active "
            "campaign session in this project. Query or inspect the existing campaign "
            "instead of creating a duplicate task session."
        )


def _check_owner_overlap(
    project_id: str, mode: str, task_id: str | None, owners: list[object],
) -> str | None:
    for owner in owners:
        owner_task_id = getattr(owner, "task_id", None)
        if mode == "task" and task_id and owner_task_id == task_id:
            continue

        scope_paths = list(getattr(owner, "scope_paths", []) or [])
        shared = [p for p in scope_paths if _is_shared_plumbing_path(p)]
        if shared:
            return (
                f"Dispatch blocked for {project_id}: live task session touches shared-plumbing paths "
                f"({shared[0]}). Treat migrations, schemas, contracts, routing, build/config, "
                "shared exports, and cross-cutting utilities as blockers to blind parallel coding."
            )
    return None


async def project_dispatch_overlap_block_reason(
    *,
    project_id: str,
    agent_slug: str,
    mode: str,
    task_id: str | None,
    owners: list[object],
    specialists: list[object],
) -> str | None:
    """Return a blocking reason when live project state makes a new specialist session unsafe."""
    if mode == "campaign":
        reason = _check_duplicate_campaign(project_id, agent_slug, specialists)
        if reason:
            return reason

    return _check_owner_overlap(project_id, mode, task_id, owners)


# --- shell helpers ---


async def _run_project_st_command(project_id: str, subcommand: str) -> str:
    import os

    from app.constants.projects import get_known_roots
    from app.services.tools._executor_bash import run_bash

    root = get_known_roots().get(project_id)
    working_dir = Path(root or ".").resolve()
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    return await run_bash(f"st -P {shlex.quote(project_id)} {subcommand}", working_dir, env)


async def _run_project_command(project_id: str, command: str) -> str:
    from app.constants.projects import get_known_roots
    from app.services.tools._executor_bash import run_bash
    from app.services.tools.project_env import build_project_env

    root = get_known_roots().get(project_id)
    working_dir = Path(root or ".").resolve()
    env = build_project_env(working_dir)
    return await run_bash(command, working_dir, env)


async def _ensure_task_lane_context(
    project_id: str, task_id: str,
) -> tuple[str | None, str | None, str | None]:
    """Return (branch, working_dir, error) for a claimed task checkpoint, claiming if needed."""
    from app.constants.projects import get_known_roots

    details = await _run_project_st_command(project_id, f"checkpoints --details {shlex.quote(task_id)}")
    if "No checkpoint found" in details:
        claim = await _run_project_st_command(project_id, f"claim {shlex.quote(task_id)}")
        if "Error:" in claim or claim.startswith("ERROR"):
            return None, None, f"Dispatch blocked for {task_id}: {claim.strip()}"
        details = await _run_project_st_command(project_id, f"checkpoints --details {shlex.quote(task_id)}")

    branch_match = _BRANCH_RE.search(details)
    branch = branch_match.group(1).strip() if branch_match else None
    working_dir = get_known_roots().get(project_id)
    if not branch or not working_dir:
        return (
            None, None,
            f"Dispatch blocked for {task_id}: unable to resolve claimed branch/checkout from checkpoint details.",
        )
    return branch, working_dir, None


async def prepare_specialist_dispatch(
    *, db: object, project_id: str, agent_slug: str, task: str,
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

    request = parse_specialist_dispatch_request(task)
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
    overlap_block = await project_dispatch_overlap_block_reason(
        project_id=project_id, agent_slug=agent_slug,
        mode=request.mode, task_id=request.task_id,
        owners=owners, specialists=specialists,
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

    branch, working_dir, lane_error = await _ensure_task_lane_context(project_id, request.task_id)
    if lane_error:
        raise ValueError(lane_error)

    return SpecialistDispatchPlan(
        event_type="dispatch_task", current_branch=branch, working_dir=working_dir,
    )
