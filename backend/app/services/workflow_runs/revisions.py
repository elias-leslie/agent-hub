"""Plan revision: add steps to a run, change or remove a pending step, while the run goes on.

Every change runs under the run lock (``_lock_run``), so it is serialized with the scheduler and with the commit of a
running step. A change bumps ``plan_revision`` on the run and appends who/what/when/before/after to ``plan_history``
in the run metadata. Only steps that have not started can change; a step that is running, completed or failed answers
``step_not_pending`` (HTTP 409) with where it stands.

Each function returns a dict with ``enqueue``: whether the caller should queue an advance (the run is running with no
step running, e.g. it was reopened, unblocked, or its last pending step was removed).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import WorkflowStep

from .engine import (
    FINISHED_RUN,
    INTEGRATION_PAUSES,
    EngineDeps,
    WorkflowRunError,
    _lock_run,
    _meta,
    _scratch,
    _set_meta,
    _steps,
    blocked_pause,
    failed_pause,
)
from .plan import DEAD, explicit_deps, schedule, validate_graph
from .policy import RunPolicy, load_policy, require_level_within_run
from .schemas import AddSteps, PlanChange, RemoveStep, RunRevision, StepDefinition, StepRevision

# Changing any of these changes the step's model chain, which is cached on the step after its first resolve.
CHAIN_FIELDS = ("agent_slug", "model_override", "allowed_models")


def _by(change: PlanChange, requested_by: str | None, request_source: str | None) -> dict[str, Any]:
    return {"changed_by": change.changed_by, "client_id": requested_by, "request_source": request_source}


async def _locked_open_run(db: AsyncSession, run_id: str, *, allow_completed: bool = False) -> Any:
    run = await _lock_run(db, run_id)
    if run is None:
        raise WorkflowRunError("not_found", "run not found")
    state = _meta(run).get("state")
    if state in FINISHED_RUN and not (allow_completed and state == "completed"):
        raise WorkflowRunError("already_finished", f"run is already {state}", state=state)
    return run


def _invalid(error: Exception) -> WorkflowRunError:
    return WorkflowRunError("invalid_plan", str(error))


def _check_graph(steps: list[Any], definitions: dict[str, dict[str, Any]]) -> None:
    """Validate the whole plan with ``definitions`` (by key) replacing those steps' stored ones."""

    nodes = []
    for step in sorted(steps, key=lambda s: s.position):
        definition = definitions.get(step.step_key, step.definition)
        nodes.append((step.step_key, definition.get("depends_on")))
    try:
        validate_graph(nodes)
    except ValueError as error:
        raise _invalid(error) from error


def _check_dependencies_alive(depends_on: list[str] | None, by_key: dict[str, Any]) -> None:
    for key in depends_on or ():
        dep = by_key.get(key)
        if dep is not None and dep.status in DEAD:
            raise WorkflowRunError(
                "invalid_plan", f"step {key} is {dep.status}; a step cannot depend on it", step_status=dep.status
            )


def _record(
    meta: dict[str, Any],
    action: str,
    change: PlanChange,
    changes: list[dict[str, Any]],
    by: dict[str, Any],
    now: float,
    **extra: Any,
) -> dict[str, Any]:
    revision = int(meta.get("plan_revision", 0)) + 1
    entry = {
        "revision": revision,
        "at": now,
        "action": action,
        "by": by,
        "reason": change.reason,
        "changes": changes,
        **extra,
    }
    return {**meta, "plan_revision": revision, "plan_history": [*meta.get("plan_history", []), entry]}


def _settle(run: Any, meta: dict[str, Any], steps: list[Any], now: float) -> bool:
    """Save the run metadata after a plan change; a run paused as blocked runs again once something can start.

    Returns whether the caller should enqueue an advance.
    """

    pause = meta.get("pause") or {}
    cap = load_policy(meta["policy"]).max_concurrent_steps
    if meta.get("state") == "needs_owner" and pause.get("reason") == "step_failed":
        # Stays paused until the owner resumes (retry, skip or fail); the list of what is blocked follows the plan.
        meta = {**meta, "pause": {**failed_pause(steps, schedule(steps, max_running=cap)), "at": pause.get("at", now)}}
    elif meta.get("state") == "needs_owner" and pause.get("reason") in INTEGRATION_PAUSES:
        # A join step (or any new work) is the way past a failed merge: the run goes on, and puts the results together
        # again when it is done.
        if any(s.status == "pending" for s in steps):
            meta = {**meta, "state": "running", "pause": None}
    elif meta.get("state") == "needs_owner" and pause.get("reason") == "blocked_dependencies":
        plan = schedule(steps, max_running=cap)
        if plan.start or not any(s.status == "pending" for s in steps):
            meta = {**meta, "state": "running", "pause": None}
        else:
            meta = {**meta, "pause": {**blocked_pause(plan), "at": now}}
    _set_meta(run, meta, now=now)
    if meta.get("state") != "running":
        return False
    # Nothing running: an advance finishes, pauses or starts the run. Something running: only when a free slot has a
    # ready step (the change made one ready, or the cap rose).
    return not any(s.status == "running" for s in steps) or bool(schedule(steps, max_running=cap).start)


def _reopen(run: Any, meta: dict[str, Any]) -> dict[str, Any]:
    """A completed run takes new work: back to active, as it was before ``_complete_run``."""

    run.status = "active"
    run.health_detail = None
    run.summary_oneliner = str(meta.get("goal") or "")[:500]
    provider_metadata = dict(run.provider_metadata or {})
    provider_metadata.pop("live_activity", None)
    run.provider_metadata = provider_metadata
    # The worktree is made again from the run branch when the next step needs it.
    return {**{k: v for k, v in meta.items() if k != "worktree_release"}, "state": "running", "pause": None}


def _result(run_id: str, meta: dict[str, Any], enqueue: bool, **extra: Any) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "state": meta["state"],
        "plan_revision": meta.get("plan_revision", 0),
        "enqueue": enqueue,
        **extra,
    }


async def add_steps(
    db: AsyncSession,
    run_id: str,
    request: AddSteps,
    *,
    requested_by: str | None = None,
    request_source: str | None = None,
    deps: EngineDeps | None = None,
) -> dict[str, Any]:
    """Append steps (positions after the last). A completed run is reopened; a failed or cancelled one is refused."""

    deps = deps or EngineDeps()
    now = deps.clock()
    run = await _locked_open_run(db, run_id, allow_completed=True)
    meta = _meta(run)
    steps = await _steps(db, run_id)
    by_key = {s.step_key: s for s in steps}
    clashes = [step.key for step in request.steps if step.key in by_key]
    if clashes:
        raise WorkflowRunError("duplicate_step", f"run already has step(s): {', '.join(clashes)}", keys=clashes)
    if request.after is not None and request.after not in by_key:
        raise WorkflowRunError("invalid_plan", f"after names unknown step {request.after!r}")

    definitions: list[dict[str, Any]] = []
    anchor = request.after
    for step in request.steps:
        definition = step.model_dump()
        if definition["depends_on"] is None and anchor is not None:
            definition["depends_on"] = [anchor]
            anchor = None
        definitions.append(definition)
    for definition in definitions:
        _check_dependencies_alive(definition["depends_on"], by_key)
        try:
            require_level_within_run(load_policy(meta["policy"]), definition)
        except ValueError as error:
            raise _invalid(error) from error
    position = max((s.position for s in steps), default=-1) + 1
    added = [
        WorkflowStep(
            id=str(uuid.uuid4()),
            run_session_id=run_id,
            step_key=definition["key"],
            position=position + index,
            definition=definition,
            status="pending",
            attempts=0,
            restarts=0,
        )
        for index, definition in enumerate(definitions)
    ]
    _check_graph([*steps, *added], {})
    for definition in definitions:
        await deps.resolve_chain(db, definition)  # unknown agent or empty route fails before anything is stored
    db.add_all(added)
    await db.flush()
    by = _by(request, requested_by, request_source)
    meta = _record(
        meta,
        "add_steps",
        request,
        [{"step": d["key"], "op": "add", "before": None, "after": d} for d in definitions],
        by,
        now,
    )
    reopened = meta["state"] == "completed"
    if reopened:
        meta = _reopen(run, meta)
    enqueue = _settle(run, meta, [*steps, *added], now)
    await db.commit()
    return _result(
        run_id, _meta(run), enqueue, reopened=reopened, added=[d["key"] for d in definitions]
    )


def _revised_definition(step: Any, revision: StepRevision) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """(new definition, changed fields before, changed fields after). Raises ValueError on an invalid result."""

    changes = revision.changes()
    new = StepDefinition(**{**step.definition, **changes}).model_dump()
    old = step.definition
    changed = [name for name in changes if old.get(name) != new.get(name)]
    return new, {n: old.get(n) for n in changed}, {n: new.get(n) for n in changed}


def _require_pending(step: Any, state: str | None) -> None:
    if step.status != "pending":
        raise WorkflowRunError(
            "step_not_pending",
            f"step {step.step_key} is {step.status}; only a pending step can be changed",
            step_status=step.status,
            state=state,
        )


async def _revise(
    db: AsyncSession,
    step: Any,
    revision: StepRevision,
    steps: list[Any],
    pending_definitions: dict[str, dict[str, Any]],
    deps: EngineDeps,
    state: str | None,
    policy: RunPolicy,
) -> dict[str, Any] | None:
    """Validate one step revision and stage it in ``pending_definitions``; the change record, or None when nothing differs."""

    _require_pending(step, state)
    if not revision.changes():
        raise WorkflowRunError("invalid_plan", "no changes given")
    try:
        new, before, after = _revised_definition(step, revision)
        require_level_within_run(policy, new)
    except ValueError as error:
        raise _invalid(error) from error
    if not before:
        return None
    if "depends_on" in after:
        _check_dependencies_alive(after["depends_on"], {s.step_key: s for s in steps})
    if any(name in before for name in CHAIN_FIELDS):
        await deps.resolve_chain(db, new)  # unknown agent or empty route is refused before anything changes
    pending_definitions[step.step_key] = new
    return {"step": step.step_key, "op": "revise", "before": before, "after": after}


def _apply(step: Any, new: dict[str, Any], change: dict[str, Any]) -> None:
    step.definition = new
    if any(name in change["before"] for name in CHAIN_FIELDS):
        # The cached chain was resolved from the old definition: resolve again at the next attempt, and let every
        # model of the new chain be tried.
        scratch = _scratch(step)
        scratch.pop("chain", None)
        scratch.update(tried=[], usage_limited=[], pinned_model=None)
        step.outcome = scratch


async def revise_step(
    db: AsyncSession,
    run_id: str,
    step_key: str,
    request: StepRevision,
    *,
    requested_by: str | None = None,
    request_source: str | None = None,
    deps: EngineDeps | None = None,
) -> dict[str, Any]:
    """Change a pending step. Anything that has started (running, completed, failed ...) answers 409."""

    deps = deps or EngineDeps()
    now = deps.clock()
    run = await _locked_open_run(db, run_id)
    meta = _meta(run)
    steps = await _steps(db, run_id)
    step = next((s for s in steps if s.step_key == step_key), None)
    if step is None:
        raise WorkflowRunError("step_not_found", f"run has no step named {step_key}")
    staged: dict[str, dict[str, Any]] = {}
    change = await _revise(db, step, request, steps, staged, deps, meta.get("state"), load_policy(meta["policy"]))
    if change is None:  # nothing differs: no new revision
        return _result(run_id, meta, False, changed=False, step=step_key)
    _check_graph(steps, staged)
    _apply(step, staged[step_key], change)
    meta = _record(meta, "revise_step", request, [change], _by(request, requested_by, request_source), now)
    enqueue = _settle(run, meta, steps, now)
    await db.commit()
    return _result(run_id, _meta(run), enqueue, changed=True, step=step_key)


async def remove_step(
    db: AsyncSession,
    run_id: str,
    step_key: str,
    request: RemoveStep | None = None,
    *,
    requested_by: str | None = None,
    request_source: str | None = None,
    deps: EngineDeps | None = None,
) -> dict[str, Any]:
    """Remove a pending step that has never run.

    Steps that name it in ``depends_on`` must be revised in the same call (``request.revise``); otherwise it is refused.
    A step on the default dependency (the one before it) simply follows the step that came before the removed one.
    """

    request = request or RemoveStep()
    deps = deps or EngineDeps()
    now = deps.clock()
    run = await _locked_open_run(db, run_id)
    meta = _meta(run)
    steps = await _steps(db, run_id)
    by_key = {s.step_key: s for s in steps}
    step = by_key.get(step_key)
    if step is None:
        raise WorkflowRunError("step_not_found", f"run has no step named {step_key}")
    _require_pending(step, meta.get("state"))
    if step.attempts:
        raise WorkflowRunError(
            "step_has_attempts",
            f"step {step_key} has {step.attempts} attempt(s) on record; cancel it instead of removing it",
            step_status=step.status,
        )
    dependents = [s.step_key for s in steps if step_key in (explicit_deps(s) or [])]
    unrevised = [k for k in dependents if k not in request.revise]
    if unrevised:
        raise WorkflowRunError(
            "has_dependents",
            f"steps {', '.join(unrevised)} depend on {step_key}; revise them in the same call or remove them first",
            dependents=unrevised,
        )
    unknown = [k for k in request.revise if k not in by_key or k == step_key]
    if unknown:
        raise WorkflowRunError("invalid_plan", f"revise names unknown or removed step(s): {', '.join(unknown)}")
    ordered = sorted(steps, key=lambda s: s.position)
    index = ordered.index(step)
    relinked = [
        s.step_key
        for s in ordered[index + 1 : index + 2]
        if explicit_deps(s) is None and s.step_key not in request.revise
    ]
    remaining = [s for s in steps if s is not step]
    staged: dict[str, dict[str, Any]] = {}
    changes: list[dict[str, Any]] = [{"step": step_key, "op": "remove", "before": step.definition, "after": None}]
    revisions: list[tuple[Any, dict[str, Any]]] = []
    for key, revision in request.revise.items():
        revise_change = await _revise(
            db, by_key[key], revision, remaining, staged, deps, meta.get("state"), load_policy(meta["policy"])
        )
        if revise_change is not None:
            changes.append(revise_change)
            revisions.append((by_key[key], revise_change))
    _check_graph(remaining, staged)
    for target, revise_change in revisions:
        _apply(target, staged[target.step_key], revise_change)
    await db.delete(step)
    await db.flush()
    meta = _record(
        meta,
        "remove_step",
        request,
        changes,
        _by(request, requested_by, request_source),
        now,
        **({"relinked": relinked} if relinked else {}),
    )
    enqueue = _settle(run, meta, remaining, now)
    await db.commit()
    return _result(run_id, _meta(run), enqueue, removed=step_key, relinked=relinked)


async def revise_run(
    db: AsyncSession,
    run_id: str,
    request: RunRevision,
    *,
    requested_by: str | None = None,
    request_source: str | None = None,
    deps: EngineDeps | None = None,
) -> dict[str, Any]:
    """Change a run-level setting while it goes on: how many steps may run at once.

    A higher cap starts ready steps at once; a lower one never stops a running step, it only holds back the next.
    """

    deps = deps or EngineDeps()
    now = deps.clock()
    run = await _locked_open_run(db, run_id)
    meta = _meta(run)
    cap = request.max_concurrent_steps
    if cap is None:
        raise WorkflowRunError("invalid_plan", "no changes given")
    current = load_policy(meta["policy"]).max_concurrent_steps
    if cap == current:
        return _result(run_id, meta, False, changed=False, max_concurrent_steps=current)
    if cap > 1 and not meta.get("repo_path"):
        raise WorkflowRunError(
            "invalid_plan", "max_concurrent_steps above 1 needs a repo_path: each running step works in its own worktree"
        )
    meta = {**meta, "policy": {**meta["policy"], "max_concurrent_steps": cap}}
    meta = _record(
        meta,
        "revise_run",
        request,
        [{"step": None, "op": "revise", "before": {"max_concurrent_steps": current}, "after": {"max_concurrent_steps": cap}}],
        _by(request, requested_by, request_source),
        now,
    )
    enqueue = _settle(run, meta, await _steps(db, run_id), now)
    await db.commit()
    return _result(run_id, _meta(run), enqueue, changed=True, max_concurrent_steps=cap)
