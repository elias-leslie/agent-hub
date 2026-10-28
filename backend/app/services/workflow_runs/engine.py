"""Durable workflow run engine: the step "effect sandwich", recovery and owner resume.

A run is a ``sessions`` row (type ``workflow``) whose ``provider_metadata["workflow"]`` holds run
state; each step is a ``workflow_steps`` row; each attempt is a child session (requested model on the
row, served models and outcome in ``provider_metadata["workflow_attempt"]``).

``advance_run`` runs one step in three parts: transaction A commits the intent (step running, attempt
session created with the chosen model, heartbeat), the executor runs with no transaction open,
transaction B commits outcome, handoff and checkpoint. A step found running with a stale heartbeat is
never replayed blindly: ``recover_stale_steps`` charges it as a failed attempt and retries it from its
git checkpoint until ``restart_limit``, then ends it visibly as failed.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Collection, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.utils.outcomes import outcome_details
from app.models import Session, SessionEventType, WorkflowStep
from app.services.event_storage import store_child_session_lifecycle_event
from app.services.session_live_activity import mark_session_completed

from . import acceptance as acceptance_runner
from .executor_common import catalog_served
from .executors import Executor, ExecutorUnavailable, StepResult, get_executor
from .live import LiveStatus, current_live
from .packet import (
    AttemptRef,
    GitState,
    HandoffPacket,
    MergeConflict,
    PriorStep,
    build_packet,
    normalize_handoff,
)
from .plan import Schedule, context_order, effective_deps, schedule
from .policy import (
    TOOLS_UNAVAILABLE,
    AttemptResult,
    Decision,
    RunPolicy,
    RunState,
    StepState,
    Unavailable,
    attempt_limit,
    attempts_exhausted,
    choose_attempt_model,
    decide_after_attempt,
    decide_stale_step,
    load_policy,
    pause_reason,
    usage_limit_cooldown,
)
from .processes import (
    ProcessIdentity,
    ProcessTracker,
    current_tracker,
    read_stat,
    stop_group,
    stop_marked,
)
from .schemas import CancelRequest, OwnerDecision, RunDefinition
from .settings import get_workflow_run_settings
from .usage import cost_of, record_attempt_cost, usage_totals
from .workspace import LaneParent, RunWorkspace, head_sha

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
ContextProvider = Callable[..., Awaitable[tuple[str, str]]]

RUN_STATES = ("running", "needs_owner", "completed", "failed", "cancelled")
FINISHED_RUN = ("completed", "failed", "cancelled")
TERMINAL_STEP = ("completed", "skipped", "cancelled")
# A step in any of these has nothing left to stop.
FINISHED_STEP = ("completed", "failed", "refused", "skipped", "cancelled")
# A step that ended without completing and without the owner's say-so: the run waits for the owner when nothing else can run.
FAILED_STEP = ("failed", "refused")


class WorkflowRunError(Exception):
    def __init__(self, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.extra = extra


# --- dependencies ------------------------------------------------------------------------------


def default_context_window(model: str) -> int | None:
    from app.constants.catalog import INACTIVE_MODEL_CATALOG_BY_ID, get_model_entry

    entry = get_model_entry(model) or INACTIVE_MODEL_CATALOG_BY_ID.get(model)
    return entry.context_window if entry is not None else None


async def resolve_agent_chain(db: AsyncSession, definition: dict[str, Any]) -> list[str]:
    """The step's ordered models: its agent's route (primary, fallbacks, escalation) with the optional
    ``model_override`` first and ``allowed_models`` as a narrowing filter."""

    from app.services.agent_model_router import resolve_model_route
    from app.services.agent_service import get_agent_service

    agent = await get_agent_service().get_by_slug(db, definition["agent_slug"])
    if agent is None:
        raise WorkflowRunError("unknown_agent", f"agent {definition['agent_slug']!r} not found")
    _, route = await resolve_model_route(db, agent)
    chain = list(route.chain)
    override = definition.get("model_override")
    if override:
        chain = [override, *(m for m in chain if m != override)]
    allowed = definition.get("allowed_models")
    if allowed:
        chain = [m for m in chain if m in allowed]
    if not chain:
        raise WorkflowRunError(
            "empty_chain", f"agent {definition['agent_slug']!r} has no usable model for this step"
        )
    return chain


async def chain_availability(models: list[str]) -> dict[str, Unavailable]:
    """Skip reasons from the shared routing pre-flight (inactive model, no credential, provider cooldown)."""

    from app.services.agent_routing_completion import route_preflight_error
    from app.services.llm_errors import RateLimitError

    blocked: dict[str, Unavailable] = {}
    for model in models:
        error = await route_preflight_error(model)
        if error is None:
            continue
        retry_after = error.retry_after if isinstance(error, RateLimitError) else None
        blocked[model] = Unavailable(str(error), float(retry_after) if retry_after else None)
    return blocked


async def trip_cooldown(provider: str, seconds: float, signature: str) -> None:
    from app.services.agent_routing_completion import trip_provider_cooldown

    await trip_provider_cooldown(provider, seconds, signature)


def default_provider_of(model: str) -> str:
    from app.routing.registry import get_provider_for_model

    return get_provider_for_model(model)


async def canonical_context(
    session_factory: SessionFactory,
    *,
    project_id: str,
    step: dict[str, Any],
    meta: dict[str, Any],
    model: str,
    provider: str,
) -> tuple[str, str]:
    """Developer context from the canonical delivery; (text, status). A failure never blocks the step."""

    from app.services.runtime_context import (
        CanonicalContextDeliveryRequest,
        build_canonical_context_delivery,
    )

    policy_context = meta["policy"]["context"]
    try:
        async with session_factory() as db:
            delivery = await build_canonical_context_delivery(
                db,
                CanonicalContextDeliveryRequest(
                    consumer_surface=policy_context["surface"],
                    consumer_profile=policy_context["profile"],
                    agent_slug=step["definition"]["agent_slug"],
                    project_id=project_id,
                    workflow_ids=list(
                        dict.fromkeys(
                            [
                                *meta.get("workflow_ids", []),
                                *step["definition"].get("workflow_ids", []),
                            ]
                        )
                    ),
                    phase=step["key"],
                    task=meta["goal"],
                    cwd=meta.get("worktree"),
                    repo_root=meta.get("repo_path"),
                    provider=provider,
                    model=model,
                ),
            )
        return delivery.rendered, str(delivery.status)
    except Exception:
        logger.warning(
            "canonical context unavailable for workflow step %s", step["key"], exc_info=True
        )
        return "", "unavailable"


@dataclass
class EngineDeps:
    session_factory: SessionFactory | None = None
    get_executor: Callable[[str], Executor] = get_executor
    resolve_chain: Callable[[AsyncSession, dict[str, Any]], Awaitable[list[str]]] = (
        resolve_agent_chain
    )
    availability: Callable[[list[str]], Awaitable[dict[str, Unavailable]]] = chain_availability
    trip_cooldown: Callable[[str, float, str], Awaitable[None]] = trip_cooldown
    provider_of: Callable[[str], str] = default_provider_of
    context_window_of: Callable[[str], int | None] = default_context_window
    context_provider: ContextProvider | None = None
    owner_only_categories: Callable[[], Collection[str]] | None = None
    test_hooks_on: Callable[[], bool] | None = None
    agent_thinking_level: Callable[[str], Awaitable[str | None]] | None = None
    # Queue another advance of a run (a ready step is waiting for a free slot); default is the Hatchet task.
    enqueue_advance: Callable[[str], Awaitable[Any]] | None = None
    clock: Callable[[], float] = time.time

    def factory(self) -> SessionFactory:
        if self.session_factory is not None:
            return self.session_factory
        from app.db import async_session

        return async_session

    async def enqueue(self, run_id: str) -> None:
        if self.enqueue_advance is not None:
            await self.enqueue_advance(run_id)
            return
        from app.workflows.workflow_run import enqueue_advance

        await enqueue_advance(run_id)

    async def thinking_level_of(self, agent_slug: str) -> str | None:
        """The agent's configured thinking level; none when it cannot be read (the executor default applies)."""

        if self.agent_thinking_level is not None:
            return await self.agent_thinking_level(agent_slug)
        from app.services.agent_service import get_agent_service

        try:
            async with self.factory()() as db:
                agent = await get_agent_service().get_by_slug(db, agent_slug)
            return agent.thinking_level if agent is not None else None
        except Exception:
            logger.warning("thinking level of agent %s unavailable", agent_slug, exc_info=True)
            return None

    def test_hooks_enabled(self) -> bool:
        if self.test_hooks_on is not None:
            return self.test_hooks_on()
        from app.config import get_settings

        return get_settings().workflow_test_hooks_enabled

    def owner_only(self) -> Collection[str]:
        if self.owner_only_categories is not None:
            return self.owner_only_categories()
        from app.config import get_settings

        return get_settings().workflow_owner_only_refusal_categories


def _dt(epoch: float) -> datetime:
    return datetime.fromtimestamp(epoch, UTC)


def _iso(epoch: float | None) -> str | None:
    return _dt(epoch).isoformat() if epoch else None


# --- helpers over rows ---------------------------------------------------------------------------


async def _lock_run(db: AsyncSession, run_id: str) -> Session | None:
    row = (
        await db.execute(
            select(Session)
            .where(Session.id == run_id, Session.session_type == "workflow")
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is not None:
        await db.refresh(row)
    return row


async def _steps(db: AsyncSession, run_id: str) -> list[WorkflowStep]:
    rows = await db.execute(
        select(WorkflowStep)
        .where(WorkflowStep.run_session_id == run_id)
        .order_by(WorkflowStep.position)
    )
    return list(rows.scalars())


def _meta(run: Session) -> dict[str, Any]:
    return dict((run.provider_metadata or {}).get("workflow") or {})


def _set_meta(run: Session, meta: dict[str, Any], *, now: float) -> None:
    run.provider_metadata = {**(run.provider_metadata or {}), "workflow": meta}
    run.last_activity_at = _dt(now)


def _scratch(step: WorkflowStep) -> dict[str, Any]:
    """Engine-owned step state kept in ``workflow_steps.outcome``: chain, tried models, hops, last attempt."""

    return dict(step.outcome or {})


def _work_of(usage: Mapping[str, Any] | None) -> int:
    """Tokens an attempt used, the measure of whether it made progress (zero for one that failed before the model ran)."""

    counts = usage or {}
    return sum(
        value
        for key in ("input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens")
        if isinstance(value := counts.get(key), int) and not isinstance(value, bool)
    )


def _unproductive_resumes(scratch: Mapping[str, Any]) -> int:
    """Usage-limit waits in a row that followed no new tokens; 0 once work was done since the previous resume."""

    if scratch.get("work_total", 0) > scratch.get("work_at_resume", 0):
        return 0
    return int(scratch.get("unproductive_resumes", 0))


def _step_state(
    step: WorkflowStep, chain: list[str] | None = None, scratch: dict[str, Any] | None = None
) -> StepState:
    scratch = _scratch(step) if scratch is None else scratch
    return StepState(
        chain=tuple(chain if chain is not None else scratch.get("chain", ())),
        tried=tuple(scratch.get("tried", ())),
        attempts=step.attempts,
        max_attempts=step.definition.get("max_attempts"),
        pinned_model=scratch.get("pinned_model"),
        usage_limited=tuple(scratch.get("usage_limited", ())),
        unproductive_resumes=_unproductive_resumes(scratch),
        acceptance_failures=scratch.get("acceptance_failures", 0),
        extra_attempts=_extra_attempts(scratch),
    )


def _extra_attempts(scratch: Mapping[str, Any]) -> int:
    """Attempts the owner granted this step past its cap, in all."""

    return int((scratch.get("extra_attempts") or {}).get("total", 0))


def _retry_after_limit(scratch: dict[str, Any]) -> None:
    """Waiting out a usage limit: the limited models may run again once the pause ends.

    The wait counts as unproductive only when no tokens were used since the previous resume.
    """

    scratch["usage_limit_resumes"] = scratch.get("usage_limit_resumes", 0) + 1
    scratch["unproductive_resumes"] = _unproductive_resumes(scratch) + (
        1 if scratch.get("work_total", 0) <= scratch.get("work_at_resume", 0) else 0
    )
    scratch["work_at_resume"] = scratch.get("work_total", 0)
    limited = set(scratch.get("usage_limited", ()))
    scratch["tried"] = [m for m in scratch.get("tried", []) if m not in limited]
    scratch["usage_limited"] = []


def _run_state(meta: dict[str, Any]) -> RunState:
    return RunState(refusals=meta.get("refusals", {}))


def _fail_run(
    run: Session, meta: dict[str, Any], steps: list[WorkflowStep], reason: str, now: float
) -> None:
    for step in steps:
        if step.status == "pending":
            step.status = "skipped"
            step.outcome = {**_scratch(step), "skipped": "run_failed"}
    meta = {**meta, "state": "failed", "pause": None, "failure": reason}
    run.status = "failed"
    run.health_detail = reason[:100]
    run.summary_oneliner = f"Workflow failed: {reason}"[:500]
    _set_meta(run, meta, now=now)


def _complete_run(run: Session, meta: dict[str, Any], now: float) -> None:
    mark_session_completed(
        run, summary="Workflow completed", termination_reason="workflow_completed"
    )
    _set_meta(run, {**meta, "state": "completed", "pause": None}, now=now)


def _cancel_run(
    run: Session, meta: dict[str, Any], steps: list[WorkflowStep], cancel: dict[str, Any], now: float
) -> None:
    """End the run as cancelled: what has not started is skipped, with the reason on each step."""

    for step in steps:
        if step.status in ("pending", "needs_owner"):
            step.status = "skipped"
            step.outcome = {**_scratch(step), "skipped": "run_cancelled"}
    reason = cancel.get("reason")
    run.status = "failed"  # the session enum has no cancelled; health_detail and the run state say which
    run.health_detail = "cancelled"
    run.summary_oneliner = f"Workflow cancelled{f': {reason}' if reason else ''}"[:500]
    _set_meta(run, {**meta, "state": "cancelled", "pause": None, "cancel": cancel}, now=now)


def _cancel_request(meta: dict[str, Any], step: WorkflowStep) -> dict[str, Any] | None:
    """The stop request that applies to a running step: its own, else the run's.

    A run that has failed stops the steps still running beside the one that failed: nothing they produce can be used.
    """

    request = _scratch(step).get("cancel") or meta.get("cancel")
    if request is None and meta.get("state") == "failed":
        return {"scope": "run", "reason": f"run failed: {meta.get('failure') or 'a step failed'}"}
    return request


def _others_running(steps: list[WorkflowStep], step: WorkflowStep) -> bool:
    return any(s is not step and s.status == "running" for s in steps)


def _pause_run(run: Session, meta: dict[str, Any], pause: dict[str, Any], now: float) -> None:
    _set_meta(run, {**meta, "state": "needs_owner", "pause": {**pause, "at": now}}, now=now)


def _describe_hop(hop: dict[str, Any]) -> str:
    category = f" ({hop['category']})" if hop.get("category") else ""
    return f"{hop['kind']}{category} on {hop['from_model']}"


# --- creation ------------------------------------------------------------------------------------


async def create_run(
    db: AsyncSession, definition: RunDefinition, *, deps: EngineDeps | None = None
) -> tuple[str, bool]:
    """Create a run and its steps. Returns (run_id, created).

    A repeated request_id returns the first run when the definition is the same; a different definition under the
    same request_id is refused (``request_id_conflict``) instead of quietly handing back the old run.
    """

    deps = deps or EngineDeps()
    fingerprint = definition_fingerprint(definition)
    if definition.request_id:
        existing = await _run_for_request(db, definition, fingerprint)
        if existing:
            return existing, False
    policy = load_policy(definition.policy)
    _require_repo_for_parallel(policy, definition.repo_path)
    for step in definition.steps:
        await deps.resolve_chain(
            db, step.model_dump()
        )  # unknown agent or empty route fails before anything is stored
    run_id = str(uuid.uuid4())
    settings = get_workflow_run_settings()
    base_sha = (
        await head_sha(definition.repo_path, definition.base_ref) if definition.repo_path else None
    )
    now = deps.clock()
    meta = {
        "state": "running",
        "goal": definition.goal,
        "repo_path": definition.repo_path,
        "base_ref": definition.base_ref,
        "base_sha": base_sha,
        "branch": f"workflow/{run_id[:8]}",
        "root": str(settings.runs_root / run_id),
        "worktree": str(settings.runs_root / run_id / "worktree"),
        "run_dir": str(settings.runs_root / run_id / "run"),
        "task_id": definition.task_id,
        "policy": policy.as_dict(),
        "refusals": {},
        "pause": None,
        "launched_by": definition.launched_by,
        "coordinator": definition.coordinator,
        "request_id": definition.request_id,
        "definition_hash": fingerprint,
        "plan_revision": 0,
        "plan_history": [],
    }
    db.add(
        Session(
            id=run_id,
            project_id=definition.project_id,
            provider="workflow",
            model="workflow",
            status="active",
            session_type="workflow",
            external_id=definition.task_id,
            request_source="workflow_run",
            current_branch=meta["branch"],
            provider_metadata={"workflow": meta},
            models_used=[],
            providers_used=[],
            summary_oneliner=definition.goal[:500],
            last_activity_at=_dt(now),
        )
    )
    await db.flush()
    for position, step in enumerate(definition.steps):
        db.add(
            WorkflowStep(
                id=str(uuid.uuid4()),
                run_session_id=run_id,
                step_key=step.key,
                position=position,
                definition=step.model_dump(),
                status="pending",
                attempts=0,
                restarts=0,
                request_id=f"{definition.request_id}:{step.key}" if definition.request_id else None,
            )
        )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await _run_for_request(db, definition, fingerprint)
        if existing:
            return existing, False
        raise
    return run_id, True


def _require_repo_for_parallel(policy: RunPolicy, repo_path: str | None) -> None:
    """Steps that run at once each need a worktree of their own, which only a repository gives them."""

    if policy.max_concurrent_steps > 1 and not repo_path:
        raise ValueError(
            "max_concurrent_steps above 1 needs a repo_path: each running step works in its own git worktree"
        )


def definition_fingerprint(definition: RunDefinition) -> str:
    """Hash of everything the caller asked for except the request id, so a repeat can be told from a different request."""

    body = json.dumps(
        definition.model_dump(mode="json", exclude={"request_id"}), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(body.encode()).hexdigest()


async def _run_for_request(db: AsyncSession, definition: RunDefinition, fingerprint: str) -> str | None:
    """The run already created for this request id; raises when it was created from a different definition."""

    request_id = definition.request_id
    found = (
        await db.execute(
            select(Session.id, Session.provider_metadata["workflow"]["definition_hash"].as_string())
            .where(
                Session.session_type == "workflow",
                Session.provider_metadata["workflow"]["request_id"].as_string() == request_id,
            )
            .limit(1)
        )
    ).first()
    if found is None:  # runs made before the request id was kept on the run: keyed on the first step
        legacy = await db.scalar(
            select(WorkflowStep.run_session_id).where(
                WorkflowStep.request_id == f"{request_id}:{definition.steps[0].key}"
            )
        )
        return legacy
    run_id, stored = found
    if stored is not None and stored != fingerprint:
        raise WorkflowRunError(
            "request_id_conflict",
            f"request_id {request_id!r} already created run {run_id} from a different definition; "
            "use a new request_id for a changed definition",
            run_id=run_id,
        )
    return run_id


# --- advance ---------------------------------------------------------------------------------------


def _start_sha(steps: list[WorkflowStep], meta: dict[str, Any]) -> str | None:
    """The worktree's last checkpoint: the newest completed step's, whatever its position (the plan can grow)."""

    done = [s for s in steps if s.status == "completed" and s.checkpoint_sha]
    done.sort(key=lambda s: (_scratch(s).get("completed_at", 0.0), s.position))
    return done[-1].checkpoint_sha if done else meta.get("base_sha")


def _lane_parents(
    steps: list[WorkflowStep], step: WorkflowStep, deps: Mapping[str, list[str]], meta: dict[str, Any]
) -> list[LaneParent]:
    """The commits a step's lane starts from: its dependencies' checkpoints in order, else the run's base commit."""

    by_key = {s.step_key: s for s in steps}
    parents = [
        LaneParent(key, by_key[key].checkpoint_sha)
        for key in deps[step.step_key]
        if by_key[key].checkpoint_sha
    ]
    return parents or [LaneParent(None, meta["base_sha"])]


async def _integrate_result(meta: dict[str, Any], steps: list[WorkflowStep]) -> dict[str, Any] | None:
    """Where a run that ran steps in lanes ends up: the finished steps nothing else builds on, on the run branch.

    A run that never used lanes has its result in the run worktree already.
    """

    if not meta.get("parallel") or not meta.get("repo_path"):
        return None
    done = [s for s in steps if s.status == "completed" and s.checkpoint_sha]
    built_on = {dep for deps in effective_deps(steps).values() for dep in deps}
    leaves = [
        LaneParent(s.step_key, s.checkpoint_sha or "")
        for s in sorted(done, key=lambda s: s.position)
        if s.step_key not in built_on
    ]
    policy = load_policy(meta["policy"])
    identity = (f"user.name={policy.git['user_name']}", f"user.email={policy.git['user_email']}")
    try:
        return await RunWorkspace.from_meta(meta, identity).integrate(leaves)
    except Exception as exc:
        logger.exception("workflow run result could not be put together")
        return {"state": "failed", "error": repr(exc), "branch": meta.get("branch"), "worktree": meta.get("worktree")}


def _prior(steps: list[WorkflowStep], step: WorkflowStep) -> list[PriorStep]:
    """Handoffs of the step's transitive dependencies, dependencies first. ``position`` is the place in that order."""

    by_key = {s.step_key: s for s in steps}
    return [
        PriorStep(
            key=s.step_key,
            position=index,
            status=s.status,
            model=_scratch(s).get("last", {}).get("served_model") or s.chosen_model,
            handoff=s.handoff,
            notes_path=_scratch(s).get("notes_path"),
        )
        for index, key in enumerate(context_order(steps, step))
        if (s := by_key[key]).status == "completed"
    ]


class _Heartbeat:
    """Keeps a running step's heartbeat fresh from a ticker and from executor events.

    Each beat also reads the durable stop request (the step's own or the run's). The first time it sees one it sets
    ``cancelled`` and runs ``on_cancel`` once, in its own task, so a slow stop never holds up the ticker.
    """

    def __init__(
        self,
        deps: EngineDeps,
        run_id: str,
        step_id: str,
        attempt_id: str,
        interval: float,
        on_cancel: Callable[[], Awaitable[None]] | None = None,
        live: LiveStatus | None = None,
        tracker: ProcessTracker | None = None,
    ) -> None:
        self.deps, self.run_id, self.step_id, self.attempt_id, self.interval = (
            deps,
            run_id,
            step_id,
            attempt_id,
            interval,
        )
        self.on_cancel = on_cancel
        self.live = live
        self.tracker = tracker
        self.cancelled = False
        self._last = deps.clock()
        self._task: asyncio.Task[None] | None = None
        self._interrupt: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()

    async def _liveness(self) -> dict[str, Any] | None:
        """The attempt's phase, time of its harness's last event and whether the harness process is alive.

        Shown, never acted on: a harness that has been quiet for a long time is thinking, not stuck. In-process
        executors have no harness (``harness_pid`` is null).
        """

        if self.live is None:
            return None
        harness = self.tracker.harness() if self.tracker is not None else None
        pid = harness.process.pid if harness is not None else None
        alive = None
        if harness is not None:
            stat = await asyncio.to_thread(read_stat, pid) if pid is not None else None
            alive = harness.process.returncode is None and stat is not None and stat.state != "Z"
        return {
            **self.live.snapshot(),
            "harness_pid": pid,
            "harness_alive": alive,
            "updated_at": self._last,
        }

    async def beat(self) -> None:
        self._last = self.deps.clock()
        cancel: dict[str, Any] | None = None
        liveness = await self._liveness()
        try:
            async with self.deps.factory()() as db:
                step = await db.get(WorkflowStep, self.step_id)
                if (
                    step is not None
                    and step.status == "running"
                    and step.current_attempt_session_id == self.attempt_id
                ):
                    step.heartbeat_at = _dt(self._last)
                    attempt = await db.get(Session, self.attempt_id, with_for_update=True)
                    if (
                        attempt is not None
                    ):  # keeps the cleanup/reaper heuristics off a live attempt
                        attempt.last_heartbeat_at = attempt.last_activity_at = _dt(self._last)
                        if liveness is not None:
                            meta = dict(attempt.provider_metadata or {})
                            meta["live_activity"] = {**(meta.get("live_activity") or {}), "workflow": liveness}
                            attempt.provider_metadata = meta
                    run = await db.get(Session, self.run_id)
                    cancel = _cancel_request(_meta(run), step) if run is not None else None
                    await db.commit()
        except Exception:
            logger.warning("workflow heartbeat failed for step %s", self.step_id, exc_info=True)
        if cancel and not self.cancelled:
            self.cancelled = True
            if self.on_cancel is not None:
                self._interrupt = asyncio.create_task(self.on_cancel())

    async def on_event(self, _event: Any) -> None:
        if self.deps.clock() - self._last >= self.interval:
            await self.beat()

    async def _loop(self) -> None:
        # Waits for the next beat or the end of the step; a beat in progress is never cut off mid-commit.
        while not self._stopped.is_set():
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stopped.wait(), self.interval)
                return
            await self.beat()

    async def __aenter__(self) -> _Heartbeat:
        self._task = asyncio.create_task(self._loop())
        return self

    async def __aexit__(self, *_exc: object) -> None:
        self._stopped.set()
        if self._task is not None:
            try:
                await self._task
            except BaseException:
                self._task.cancel()
                raise
        if self._interrupt is not None:
            with contextlib.suppress(Exception):
                await self._interrupt


async def _record_process(deps: EngineDeps, attempt_id: str, entry: dict[str, Any]) -> None:
    """Note a process the attempt started (pid, group, start time) on the attempt, so recovery can find it."""

    async with deps.factory()() as db:
        attempt = await db.get(Session, attempt_id, with_for_update=True)
        if attempt is None:
            return
        meta = dict(attempt.provider_metadata or {})
        detail = dict(meta.get("workflow_attempt") or {})
        detail["processes"] = [*detail.get("processes", []), entry]
        attempt.provider_metadata = {**meta, "workflow_attempt": detail}
        await db.commit()


@dataclass
class _Intent:
    run_id: str
    step_id: str
    step_key: str
    position: int
    definition: dict[str, Any]
    attempt_id: str
    attempt_no: int
    model: str
    provider: str
    chain: list[str]
    tried: list[str]
    usage_limited: list[str]
    executor: str | None
    reset: bool
    hop: dict[str, Any] | None
    partial_path: str | None
    start_sha: str | None
    meta: dict[str, Any]
    prior: list[PriorStep]
    project_id: str
    # What the step's failed acceptance commands printed, for the retry's packet.
    acceptance_note: str | None = None
    # The step's own worktree (named by the step) and the commits it starts from; None runs in the run's worktree.
    lane: str | None = None
    parents: list[LaneParent] = field(default_factory=list)
    lane_record: dict[str, Any] | None = None
    # Another ready step has a free slot: the caller queues one more advance.
    more: bool = False


def blocked_pause(plan: Schedule) -> dict[str, Any]:
    """The pause for a run whose pending steps can never start, naming each step and what blocks it."""

    blocked = plan.blocked
    return {
        "reason": "blocked_dependencies",
        "step_key": next(iter(blocked), None),
        "blocked": {key: r.as_dict() for key, r in blocked.items()},
    }


def _failure_of(step: WorkflowStep) -> dict[str, Any]:
    last = _scratch(step).get("last") or {}
    return {"status": step.status, "reason": last.get("reason"), "error": (last.get("error") or "")[:300] or None}


def failed_steps(steps: Sequence[WorkflowStep]) -> list[WorkflowStep]:
    return sorted((s for s in steps if s.status in FAILED_STEP), key=lambda s: s.position)


def failed_pause(steps: Sequence[WorkflowStep], plan: Schedule) -> dict[str, Any]:
    """The pause for a run with nothing left to run and a step that failed: each failed step, and the steps it blocks."""

    failed = {s.step_key: _failure_of(s) for s in failed_steps(steps)}
    return {
        "reason": "step_failed",
        "step_key": next(iter(failed), None),
        "failed": failed,
        "blocked": {key: r.as_dict() for key, r in plan.blocked.items()},
    }


def stuck_pause(steps: Sequence[WorkflowStep], plan: Schedule) -> dict[str, Any]:
    """Why a run with nothing running cannot go on: a failed step, else pending steps blocked by skipped or cancelled ones."""

    return failed_pause(steps, plan) if failed_steps(steps) else blocked_pause(plan)


def _pause_for_step(
    run: Session, step: WorkflowStep, meta: dict[str, Any], reason: str, now: float, **extra: Any
) -> None:
    step.status = "needs_owner"
    _pause_run(run, meta, {"reason": reason, "step_key": step.step_key, **extra}, now)


async def _commit_intent(run_id: str, deps: EngineDeps) -> tuple[dict[str, Any], _Intent | None]:
    from app.api.complete.session_repo import apply_execution_metadata

    now = deps.clock()
    async with deps.factory()() as db:
        run = await _lock_run(db, run_id)
        if run is None:
            return {"next": "stop", "reason": "missing"}, None
        meta = _meta(run)
        if meta.get("state") != "running":
            return {"next": "stop", "reason": f"run_{meta.get('state')}"}, None
        steps = await _steps(db, run_id)
        run_policy = load_policy(meta["policy"])
        running = any(s.status == "running" for s in steps)
        if not any(s.status == "pending" for s in steps):
            if running:
                return {"next": "stop", "reason": "step_running"}, None
            if failed_steps(steps):  # the work is done except for what failed: the owner decides
                _pause_run(run, meta, failed_pause(steps, schedule(steps)), now)
                await db.commit()
                return {"next": "stop", "reason": "step_failed"}, None
            result = await _integrate_result(meta, steps)
            _complete_run(run, {**meta, **({"result": result} if result else {})}, now)
            await db.commit()
            return {"next": "stop", "reason": "completed"}, None
        plan = schedule(steps, max_running=run_policy.max_concurrent_steps)
        if not plan.start:
            if running:  # at the cap, or everything left waits on a running step: its end queues the next advance
                return {"next": "stop", "reason": "step_running"}, None
            # Nothing can start: every pending step waits on one that will never complete. A failed step is the owner's
            # call (retry, skip or end the run); otherwise the owner or coordinator revises the plan (the step is
            # skipped or cancelled; point its dependents elsewhere or remove them).
            pause = stuck_pause(steps, plan)
            _pause_run(run, meta, pause, now)
            await db.commit()
            return {"next": "stop", "reason": pause["reason"]}, None
        step = plan.start[0]
        scratch = _scratch(step)
        if not scratch.get("chain"):
            try:
                scratch["chain"] = await deps.resolve_chain(db, step.definition)
            except Exception as exc:
                _pause_for_step(run, step, meta, "no_agent_route", now, error=str(exc))
                await db.commit()
                return {"next": "stop", "reason": "no_agent_route"}, None
        state = _step_state(step, scratch["chain"])
        cap = attempts_exhausted(
            state.attempts, state.max_attempts, load_policy(meta["policy"]), state.extra_attempts
        )
        if cap:  # no path may start another attempt past the cap
            step.status = "failed"
            step.outcome = {**scratch, "last": {**(scratch.get("last") or {}), "reason": cap}}
            await db.commit()
            return {"next": "continue", "reason": cap}, None  # the other steps go on; the next advance decides
        untried = [m for m in state.chain if m not in state.tried]
        unavailable = await deps.availability([*untried, *state.usage_limited])
        choice = choose_attempt_model(state, unavailable, now)
        if choice.model is None:
            reason = pause_reason(choice, state, load_policy(meta["policy"]))
            if reason == "usage_limit_wait":
                _retry_after_limit(scratch)
            step.outcome = scratch
            resume_after = choice.wait_until if reason == "usage_limit_wait" else None
            _pause_for_step(run, step, meta, reason, now, resume_after=resume_after)
            await db.commit()
            return {"next": "stop", "reason": reason, "resume_after": resume_after}, None
        chain = scratch["chain"]
        provider = deps.provider_of(choice.model)
        executor = step.definition.get("executor") or load_policy(
            meta["policy"]
        ).executor_for_provider.get(provider)
        hop = scratch.get("hop")
        attempt_id = str(uuid.uuid4())
        attempt_no = step.attempts + 1
        attempt = Session(
            id=attempt_id,
            project_id=run.project_id,
            provider=provider[:20],
            model=choice.model,
            status="active",
            session_type="agent",
            parent_session_id=run_id,
            external_id=run.external_id,
            request_source="workflow_run",
            agent_slug=step.definition["agent_slug"][:50],
            current_branch=meta["branch"],
            models_used=[],
            providers_used=[],
            last_activity_at=_dt(now),
            summary_oneliner=f"{step.step_key} attempt {attempt_no} on {choice.model}"[:500],
            provider_metadata={
                "harness": "agent_hub",
                "workflow_attempt": {
                    "run_id": run_id,
                    "step_id": step.id,
                    "step_key": step.step_key,
                    "attempt": attempt_no,
                    "executor": executor,
                    "hop": hop,
                    "started_at": now,
                },
            },
        )
        db.add(attempt)
        await db.flush()
        # Same fields the session UI reads: requested is the step's primary, effective is what this attempt runs.
        apply_execution_metadata(
            attempt,
            requested_model=choice.model,
            effective_model=choice.model,
            fallback_used=choice.model != chain[0],
            fallback_reason=_describe_hop(hop) if hop else None,
        )
        reset = bool(scratch.pop("reset_on_next", False))
        partial_path = scratch.get("partial_path")
        step.status = "running"
        step.attempts = attempt_no
        step.current_attempt_session_id = attempt_id
        step.chosen_model = choice.model
        step.heartbeat_at = _dt(now)
        step.outcome = {**scratch, "pinned_model": None}
        run.last_activity_at = _dt(now)
        await store_child_session_lifecycle_event(
            db, attempt, SessionEventType.CHILD_SESSION_STARTED
        )
        # More than one step may run: each gets a lane of its own, and the run stays on lanes from then on.
        lane = (
            step.step_key
            if meta.get("repo_path") and (run_policy.max_concurrent_steps > 1 or meta.get("parallel"))
            else None
        )
        if lane and not meta.get("parallel"):
            meta = {**meta, "parallel": True}
            _set_meta(run, meta, now=now)
        intent = _Intent(
            run_id=run_id,
            step_id=step.id,
            step_key=step.step_key,
            position=step.position,
            definition=dict(step.definition),
            attempt_id=attempt_id,
            attempt_no=attempt_no,
            model=choice.model,
            provider=provider,
            chain=list(chain),
            tried=list(state.tried),
            usage_limited=list(state.usage_limited),
            executor=executor,
            reset=reset,
            hop=hop,
            partial_path=partial_path,
            start_sha=_start_sha(steps, meta),
            meta=meta,
            prior=_prior(steps, step),
            project_id=run.project_id,
            acceptance_note=scratch.get("acceptance_note"),
            lane=lane,
            parents=_lane_parents(steps, step, plan.deps, meta) if lane else [],
            lane_record=scratch.get("workspace") if lane else None,
            more=len(plan.start) > 1,
        )
        await db.commit()
    return {}, intent


def _identity(policy: RunPolicy) -> tuple[str, ...]:
    return (f"user.name={policy.git['user_name']}", f"user.email={policy.git['user_email']}")


def _workspace_of(intent: _Intent, policy: RunPolicy, record: Mapping[str, Any] | None = None) -> RunWorkspace:
    """The step's workspace: its lane, or the run's worktree."""

    if intent.lane:
        return RunWorkspace.lane_of(
            intent.meta, intent.lane, _identity(policy), (record or {}).get("base_sha")
        )
    return RunWorkspace.from_meta(intent.meta, _identity(policy))


async def _record_workspace(deps: EngineDeps, intent: _Intent, record: dict[str, Any]) -> None:
    """Keep where the attempt works (worktree, branch, base commit, merge result) on the attempt and the step."""

    async with deps.factory()() as db:
        await _lock_run(db, intent.run_id)  # taken in the order cancel and the outcome take it
        step = await db.get(WorkflowStep, intent.step_id)
        attempt = await db.get(Session, intent.attempt_id, with_for_update=True)
        if step is None or attempt is None:
            return
        await db.refresh(step)
        scratch = _scratch(step)
        scratch["workspace"] = record
        step.outcome = scratch
        meta = dict(attempt.provider_metadata or {})
        detail = {**(meta.get("workflow_attempt") or {}), "workspace": record}
        attempt.provider_metadata = {**meta, "workflow_attempt": detail}
        await db.commit()


async def _prepare_lane(intent: _Intent, workspace: RunWorkspace, deps: EngineDeps) -> dict[str, Any]:
    """The step's lane: made from its dependencies' checkpoints, or kept as it is for a further attempt.

    A lane is made again only when the dependencies it was made from are no longer the step's (the plan was revised).
    """

    wanted = [p.as_dict() for p in intent.parents]
    record = intent.lane_record
    if record and record.get("parents") == wanted and await asyncio.to_thread(workspace.worktree.exists):
        if intent.reset:  # restart after a crash: back to where the lane started
            record = await workspace.reset_lane(record)
    else:
        record = await workspace.prepare_lane(intent.parents)
    await _record_workspace(deps, intent, record)
    return record


async def _run_effect(intent: _Intent, deps: EngineDeps) -> tuple[StepResult, dict[str, Any]]:
    """The external effect: prepare the worktree, build the packet, run the executor."""

    meta, policy = intent.meta, load_policy(intent.meta["policy"])
    workspace = _workspace_of(intent, policy)
    info: dict[str, Any] = {}
    commands = acceptance_runner.commands_of(intent.definition)
    try:
        start_sha = intent.start_sha
        merge_conflict: MergeConflict | None = None
        if intent.lane:
            record = await _prepare_lane(intent, workspace, deps)
            workspace = _workspace_of(intent, policy, record)
            start_sha = record["start_sha"] or record["base_sha"]
            info["workspace"] = record
            merge_conflict = await _merge_conflict_of(workspace, record)
            meta = {**meta, "worktree": str(workspace.worktree)}  # the step's context is read from its own tree
        else:
            await workspace.ensure()
            if intent.reset:  # restart after a crash: back to the step's checkpoint
                await workspace.reset(intent.start_sha)
            info["workspace"] = {
                "lane": None,
                "worktree": str(workspace.worktree),
                "branch": workspace.branch,
                "base_sha": meta.get("base_sha"),
                "start_sha": intent.start_sha,
            }
        git: GitState = await workspace.git_state()
        provider_fn = deps.context_provider or (
            lambda **kw: canonical_context(deps.factory(), **kw)
        )
        context, info["context_status"] = await provider_fn(
            project_id=intent.project_id,
            step={"key": intent.step_key, "definition": intent.definition},
            meta=meta,
            model=intent.model,
            provider=intent.provider,
        )
        window = deps.context_window_of(intent.model) or policy.default_context_window
        partial_kwargs: dict[str, Any] = {}
        if intent.hop and intent.partial_path:
            saved = await workspace.read_json(intent.partial_path)
            partial_kwargs = {
                "partial_from": intent.hop,
                "partial_diff": await workspace.diff_since(start_sha),
                "partial_outputs": saved.get("progress", []),
            }
        elif intent.hop:
            partial_kwargs = {
                "partial_from": intent.hop,
                "partial_diff": await workspace.diff_since(start_sha),
            }
        packet: HandoffPacket = build_packet(
            run_goal=meta["goal"],
            step_key=intent.step_key,
            instructions=intent.definition["instructions"],
            acceptance=[c["cmd"] for c in commands],
            git=git,
            prior_steps=intent.prior,
            run_dir=str(workspace.run_dir),
            context_window=window,
            budget_fraction=policy.packet_budget_fraction,
            context=context,
            retry_label=(
                f"takeover: {_describe_hop(intent.hop)}"
                if intent.hop
                else "acceptance failed"
                if intent.acceptance_note
                else None
            ),
            previous_attempt_note=intent.acceptance_note,
            merge_conflict=merge_conflict,
            **partial_kwargs,
        )
        packet = replace(
            packet,
            # The step's own effort wins over the agent's thinking level in every executor.
            thinking_level=intent.definition.get("effort")
            or await deps.thinking_level_of(intent.definition["agent_slug"]),
            level=intent.definition.get("level"),
            attempt=AttemptRef(
                intent.attempt_id,
                intent.run_id,
                intent.project_id,
                intent.definition["agent_slug"],
            ),
        )
        if deps.test_hooks_enabled() and intent.definition.get("test_hooks"):
            packet = replace(packet, test_hooks=intent.definition["test_hooks"])
        stem = f"packets/{intent.position:02d}-{intent.step_key}-a{intent.attempt_no}"
        info["packet_path"] = await workspace.write_note(f"{stem}.md", packet.render())
        info["packet"] = packet.as_dict()
        if not intent.executor:
            raise ExecutorUnavailable(f"no executor kind for provider {intent.provider!r}")
        executor = deps.get_executor(intent.executor)
    except ExecutorUnavailable as exc:
        return StepResult("failed", error=f"executor_unavailable: {exc}"), info
    except Exception as exc:
        logger.exception("workflow step %s setup failed", intent.step_key)
        return StepResult("failed", error=f"setup_failed: {exc!r}"), info
    tracker = ProcessTracker(
        intent.attempt_id, lambda entry: _record_process(deps, intent.attempt_id, entry)
    )
    grace = policy.process_stop_grace_seconds
    live = LiveStatus()
    work: asyncio.Task[StepResult] | None = None

    async def run_step() -> StepResult:
        try:
            result = await executor.run(
                packet, intent.model, workspace.worktree, workspace.run_dir, heartbeat.on_event
            )
        except Exception as exc:
            logger.exception("workflow step %s executor crashed", intent.step_key)
            result = StepResult("failed", error=f"executor_crashed: {exc!r}")
        # The runner, not the agent, decides the step is done; still under the heartbeat so a slow command is not
        # taken for a stalled step.
        if commands and result.status == "completed" and normalize_handoff(result.handoff):
            info["acceptance"] = await acceptance_runner.run_acceptance(
                commands,
                workspace.worktree,
                tail_chars=policy.acceptance_output_tail_chars,
                drain_seconds=policy.acceptance_drain_seconds,
            )
        return result

    async def interrupt() -> None:
        """Stop the attempt's processes (SIGTERM, then SIGKILL after the grace), then let the work finish or cancel it."""

        await tracker.stop_all(grace)
        if work is not None:
            await asyncio.wait({work}, timeout=grace)
            work.cancel()  # no-op when it has finished

    async with _Heartbeat(
        deps,
        intent.run_id,
        intent.step_id,
        intent.attempt_id,
        policy.heartbeat_interval_seconds,
        on_cancel=interrupt,
        live=live,
        tracker=tracker,
    ) as heartbeat:
        await heartbeat.beat()  # a stop asked for before the executor starts is seen now, not an interval later
        if heartbeat.cancelled:
            result = StepResult("failed", error="cancelled")
        else:
            token = current_tracker.set(tracker)  # the executor's task starts with a copy of this context
            live_token = current_live.set(live)
            try:
                work = asyncio.create_task(run_step())
            finally:
                current_tracker.reset(token)
                current_live.reset(live_token)
            try:
                result = await work
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if not heartbeat.cancelled or (current is not None and current.cancelling()):
                    raise  # the worker itself is being stopped, not a step cancel
                result = StepResult("failed", error="cancelled")
            finally:
                await tracker.stop_all(grace)  # nothing the attempt started outlives it, however it ended
            if heartbeat.cancelled:
                result = replace(result, status="failed", handoff=None, error="cancelled")
    return result, info


async def _merge_conflict_of(workspace: RunWorkspace, record: Mapping[str, Any]) -> MergeConflict | None:
    """What a join step must resolve before its own work: conflicted files still holding markers, merges still to do."""

    if record.get("merge_result") != "conflict":
        return None
    files = await workspace.unresolved(record["conflict_files"])
    pending = [(m["step"], m["sha"]) for m in record["merges"] if m["result"] == "pending"]
    if not files and not pending:
        return None
    conflicted = next((m["step"] for m in record["merges"] if m["result"] == "conflict"), None)
    return MergeConflict(conflicted, files, pending)


def _usage_limited(result: StepResult) -> bool:
    return result.outcome is not None and result.outcome.kind == "usage_limit"


async def advance_run(run_id: str, *, deps: EngineDeps | None = None) -> dict[str, Any]:
    """Run the next eligible step of a run. ``next`` tells the caller whether to enqueue another advance."""

    deps = deps or EngineDeps()
    early, intent = await _commit_intent(run_id, deps)
    if intent is None:
        return early
    if intent.more:  # a ready step has a free slot: it gets an advance of its own and runs beside this one
        try:
            await deps.enqueue(run_id)
        except Exception:
            logger.warning("could not queue a parallel advance for run %s", run_id, exc_info=True)
    result, info = await _run_effect(intent, deps)
    # Served ids are catalog ids from here on: the same model spelled differently by an executor is not a switch.
    served_ids = catalog_served(intent.model, result.served_models)
    if served_ids != list(result.served_models):
        info["served_reported"] = list(result.served_models)
        result = replace(result, served_models=served_ids)
    policy = load_policy(intent.meta["policy"])
    workspace = _workspace_of(intent, policy, info.get("workspace"))
    handoff = normalize_handoff(result.handoff) if result.status == "completed" else None
    checkpoint: str | None = None
    notes_path: str | None = None
    partial_path: str | None = None
    accepted = acceptance_runner.passed(info.get("acceptance", []))
    if handoff is not None and accepted:  # a step that failed acceptance is not checkpointed as done
        try:
            notes_path = await workspace.write_note(
                f"steps/{intent.position:02d}-{intent.step_key}/handoff.json",
                {
                    "step": intent.step_key,
                    "model": intent.model,
                    "served_models": list(result.served_models),
                    "handoff": handoff,
                    "transcript_path": result.transcript_path,
                },
            )
            checkpoint = await workspace.checkpoint(
                f"workflow {intent.step_key}: {handoff['summary'][:60]}",
                conflict_files=(info.get("workspace") or {}).get("conflict_files", []),
            )
        except Exception as exc:
            logger.exception("workflow step %s checkpoint failed", intent.step_key)
            result = StepResult(
                "failed",
                result.served_models,
                usage=result.usage,
                error=f"checkpoint_failed: {exc!r}",
            )
            handoff = None
    if handoff is None and result.progress:
        partial_path = await workspace.write_note(
            f"steps/{intent.position:02d}-{intent.step_key}/partial-a{intent.attempt_no}.json",
            {"model": intent.model, "progress": list(result.progress)},
        )
    now = deps.clock()
    if result.outcome is not None and result.outcome.kind == "usage_limit":
        # Same shared provider cooldown a rate limit trips, held until the limit resets.
        await deps.trip_cooldown(
            intent.provider,
            usage_limit_cooldown(result.outcome, policy, now),
            f"usage_limit:{intent.provider}",
        )
    limited = [*intent.usage_limited, *([intent.model] if _usage_limited(result) else [])]
    unavailable = await deps.availability(
        [m for m in intent.chain if m not in {*intent.tried, intent.model}]
        + [m for m in dict.fromkeys(limited)]
        # The requested model too: an acceptance retry goes back to it only while it is still eligible.
        + [intent.model]
    )
    outcome = await _commit_outcome(
        run_id,
        intent,
        result,
        handoff,
        checkpoint,
        notes_path,
        partial_path,
        unavailable,
        info,
        deps,
    )
    if intent.lane and outcome.get("action") == "complete":
        # The step's checkpoint is on its branch; the directory is no longer needed.
        try:
            await workspace.retire_lane()
        except Exception:
            logger.warning("workflow step %s: lane directory not removed", intent.step_key, exc_info=True)
    return outcome


async def _commit_outcome(
    run_id: str,
    intent: _Intent,
    result: StepResult,
    handoff: dict[str, Any] | None,
    checkpoint: str | None,
    notes_path: str | None,
    partial_path: str | None,
    unavailable: dict[str, Unavailable],
    info: dict[str, Any],
    deps: EngineDeps,
) -> dict[str, Any]:
    now = deps.clock()
    async with deps.factory()() as db:
        run = await _lock_run(db, run_id)
        step = await db.get(WorkflowStep, intent.step_id)
        attempt = await db.get(Session, intent.attempt_id)
        if run is None or step is None or attempt is None:
            return {"next": "stop", "reason": "missing"}
        await db.refresh(step)
        if step.status != "running" or step.current_attempt_session_id != intent.attempt_id:
            return {"next": "stop", "reason": "attempt_abandoned"}
        meta = _meta(run)
        policy = load_policy(meta["policy"])
        # Read under the run lock, so a stop asked for while the step finished still wins.
        cancel = _cancel_request(meta, step)
        scratch = _scratch(step)
        scratch["work_total"] = scratch.get("work_total", 0) + _work_of(result.usage)
        decision = decide_after_attempt(
            model=intent.model,
            result=AttemptResult(
                result.status,
                result.outcome,
                handoff is not None,
                result.error,
                acceptance_passed=(
                    acceptance_runner.passed(info["acceptance"]) if "acceptance" in info else None
                ),
                cancelled=cancel is not None,
            ),
            step=_step_state(step, scratch=scratch),
            run=_run_state(meta),
            policy=policy,
            owner_only_categories=deps.owner_only(),
            unavailable=unavailable,
            now=now,
        )
        served = list(result.served_models) or [intent.model]
        _finish_attempt(attempt, intent, result, decision, served, info, now, cancel)
        await record_attempt_cost(
            db,
            session_id=attempt.id,
            model=served[-1],
            executor=intent.executor,
            usage=result.usage,
        )
        steps = await _steps(db, run_id)
        last = {
            "attempt": intent.attempt_no,
            "model": intent.model,
            "served_models": served,
            "served_model": served[-1],
            "status": result.status,
            "kind": decision.kind,
            "reason": decision.reason,
            "category": decision.category,
            "error": result.error,
            "attempt_session_id": intent.attempt_id,
        }
        scratch.update(last=last, tried=[*scratch.get("tried", []), intent.model])
        if _usage_limited(result):
            scratch["usage_limited"] = list(
                dict.fromkeys([*scratch.get("usage_limited", []), intent.model])
            )
        if decision.kind == "acceptance":
            scratch["acceptance_failures"] = scratch.get("acceptance_failures", 0) + 1
        if decision.reason == "acceptance_failed":
            scratch["acceptance_note"] = acceptance_runner.failure_note(info["acceptance"])
        else:
            scratch.pop("acceptance_note", None)
        if decision.hop:
            scratch["hops"] = [*scratch.get("hops", []), decision.hop]
        if notes_path:
            scratch["notes_path"] = notes_path
        scratch["partial_path"] = partial_path
        meta = {**meta, "refusals": decision.refusals}
        step.heartbeat_at = _dt(now)
        if decision.action == "complete":
            step.status, step.handoff, step.checkpoint_sha = "completed", handoff, checkpoint
            scratch.update(hop=None, partial_path=None, pinned_model=None, completed_at=now)
            if intent.lane and isinstance(scratch.get("workspace"), dict):
                # The lane directory goes once this commits; the branch and the checkpoint stay.
                scratch["workspace"] = {**scratch["workspace"], "retired": True, "checkpoint_sha": checkpoint}
        elif decision.action == "retry":
            step.status = "pending"
            scratch.update(hop=decision.hop, pinned_model=decision.next_model)
        elif decision.action == "fail":
            # The run goes on with every step that does not depend on this one; it waits for the owner only when
            # nothing else can run.
            step.status = "failed"
        elif decision.action == "cancelled":
            # Stays cancelled: no next model, no retry. A run-level request ends the run; a step-level one leaves
            # the run to carry on with its other steps, like a skip.
            step.status = "cancelled"
            scratch.update(hop=None, pinned_model=None, cancel=cancel)
            if meta.get("cancel") and not _others_running(steps, step):
                _cancel_run(run, meta, steps, meta["cancel"], now)  # the last running step to stop ends the run
        else:
            if decision.reason == "usage_limit_wait":
                _retry_after_limit(scratch)
            _pause_for_step(
                run,
                step,
                meta,
                decision.reason,
                now,
                category=decision.category,
                resume_after=decision.wait_until,
                **({"error": result.error} if decision.reason == TOOLS_UNAVAILABLE else {}),
            )
        step.outcome = scratch
        if _meta(run)["state"] == "running":
            _set_meta(run, meta, now=now)
        await store_child_session_lifecycle_event(
            db, attempt, SessionEventType.CHILD_SESSION_RESULT
        )
        state = _meta(run)["state"]
        await db.commit()
    return {
        "next": "continue" if state == "running" else "stop",
        "reason": decision.reason,
        "step": intent.step_key,
        "action": decision.action,
        "run_state": state,
    }


def _attempt_cost(usage: Mapping[str, Any] | None) -> dict[str, Any]:
    """One attempt's cost with its basis and source, for display; ``usd`` is null when it could not be priced."""

    cost, basis, source = cost_of(usage or {})
    return {"usd": cost, "basis": basis, "source": source}


def _attempt_outcome(
    intent: _Intent, result: StepResult, decision: Decision, cancel: dict[str, Any] | None
) -> dict[str, Any] | None:
    """The attempt's outcome: what the provider said, or ``cancelled`` with the request's reason."""

    if decision.action == "cancelled":
        reason = (cancel or {}).get("reason")
        return {
            "kind": "cancelled",
            "requested_model": intent.model,
            **({"explanation": reason} if reason else {}),
        }
    return outcome_details(result.outcome) if result.outcome else None


def _finish_attempt(
    attempt: Session,
    intent: _Intent,
    result: StepResult,
    decision: Decision,
    served: list[str],
    info: dict[str, Any],
    now: float,
    cancel: dict[str, Any] | None = None,
) -> None:
    from app.api.complete.session_repo import apply_execution_metadata
    from app.services.agent_routing_completion import format_fallback_reason

    attempt.provider_metadata = dict(
        attempt.provider_metadata or {}
    )  # new object so the update is persisted
    assert attempt.provider_metadata is not None
    hop = intent.hop
    apply_execution_metadata(
        attempt,
        requested_model=intent.model,
        effective_model=intent.model,
        fallback_used=intent.model != intent.chain[0],
        fallback_reason=_describe_hop(hop) if hop else None,
        served_model=served[-1],
    )
    detail = {
        **attempt.provider_metadata.get("workflow_attempt", {}),
        "served_models": served,
        "outcome": _attempt_outcome(intent, result, decision, cancel),
        "usage": dict(result.usage),
        "error": None if decision.action == "cancelled" else result.error,
        "native_session_id": result.native_session_id,
        "transcript_path": result.transcript_path,
        "tools": list(result.tools) if result.tools is not None else None,
        "served_reported": info.get("served_reported"),
        "decision": {"action": decision.action, "reason": decision.reason},
        "next_hop": decision.hop,
        "finished_at": now,
        "context_status": info.get("context_status"),
        "acceptance": info.get("acceptance"),
        "packet": info.get("packet"),
        "packet_path": info.get("packet_path"),
    }
    if info.get("workspace"):
        detail["workspace"] = info["workspace"]
    attempt.provider_metadata = {**attempt.provider_metadata, "workflow_attempt": detail}
    attempt.models_used = list(dict.fromkeys([*(attempt.models_used or []), *served]))
    attempt.last_activity_at = _dt(now)
    served_note = f" (served {', '.join(served)})" if served != [intent.model] else ""
    ended = decision.reason if decision.action != "complete" else "completed"
    if result.error and decision.action not in ("complete", "cancelled"):
        ended = f"{ended} - {format_fallback_reason(RuntimeError(result.error))}"
    attempt.summary_oneliner = (
        f"{intent.step_key} attempt {intent.attempt_no} on {intent.model}{served_note}: {ended}"[
            :500
        ]
    )
    if decision.action == "complete":
        mark_session_completed(
            attempt,
            summary=attempt.summary_oneliner,
            termination_reason="workflow_attempt_completed",
        )
    else:
        attempt.status = "failed"
        attempt.health_detail = decision.reason[:100]


# --- recovery --------------------------------------------------------------------------------------


async def recover_stale_steps(deps: EngineDeps | None = None) -> list[str]:
    """Charge stale running steps, retry or fail them, and return run ids that need another advance.

    Also returns runs paused on a usage limit whose window has reset (resumed here) and runs that are
    "running" with pending steps but no live step and no recent activity (a lost enqueue).
    """

    deps = deps or EngineDeps()
    now = deps.clock()
    to_advance: list[str] = []
    async with deps.factory()() as db:
        running = (
            await db.execute(
                select(WorkflowStep.id, WorkflowStep.run_session_id).where(
                    WorkflowStep.status == "running"
                )
            )
        ).all()
        runs_active = (
            (
                await db.execute(
                    select(Session.id).where(
                        Session.session_type == "workflow", Session.status == "active"
                    )
                )
            )
            .scalars()
            .all()
        )
    for step_id, run_id in running:
        if await _recover_one(step_id, run_id, deps, now) and run_id not in to_advance:
            to_advance.append(run_id)  # one advance is enough: each one starts a step and queues the next if room is left
    for run_id in runs_active:
        if run_id not in to_advance and await _resume_if_due(run_id, deps, now):
            to_advance.append(run_id)
    return to_advance


async def _stop_orphans(attempt: Session | None, grace: float) -> list[dict[str, Any]]:
    """Stop the process groups a stale attempt recorded; each result is the recorded entry plus ``recovery``.

    A group is signalled only when its leader still has the recorded start time (see ``processes.inspect_group``);
    a pid that has been reused, or a group that is already gone, is left alone.
    """

    if attempt is None:
        return []
    recorded = ((attempt.provider_metadata or {}).get("workflow_attempt") or {}).get("processes") or []
    results: list[dict[str, Any]] = []
    for entry in recorded:
        identity = ProcessIdentity.from_dict(entry)
        outcome = "unrecorded" if identity is None else await stop_group(identity, attempt.id, grace)
        results.append({**entry, "recovery": outcome})
    # What the harness started outside its group (a tool in a session of its own) carries the attempt's marker.
    results += [{"kind": "tool_process", **found} for found in await stop_marked(attempt.id, grace)]
    return results


async def _recover_one(step_id: str, run_id: str, deps: EngineDeps, now: float) -> bool:
    async with deps.factory()() as db:
        run = await _lock_run(db, run_id)
        step = await db.get(WorkflowStep, step_id)
        if run is None or step is None:
            return False
        await db.refresh(step)
        meta = _meta(run)
        if step.status != "running":
            return False
        policy = load_policy(meta["policy"])
        heartbeat = step.heartbeat_at.timestamp() if step.heartbeat_at else 0.0
        if now - heartbeat < policy.stale_after_seconds:
            return False
        attempt = (
            await db.get(Session, step.current_attempt_session_id)
            if step.current_attempt_session_id
            else None
        )
        # The old harness may still be writing in the worktree: its process group is stopped first, and the step is
        # only charged, reset or restarted once nothing of it is left.
        orphans = await _stop_orphans(attempt, policy.process_stop_grace_seconds)
        if any(o["recovery"] == "survived" for o in orphans):
            logger.warning("workflow step %s: a recorded process survived SIGKILL; not recovering yet", step.step_key)
            return False
        scratch = _scratch(step)
        cancel = _cancel_request(meta, step)
        verdict = decide_stale_step(
            restarts=step.restarts,
            attempts=step.attempts,
            max_attempts=step.definition.get("max_attempts"),
            policy=policy,
            cancelled=cancel is not None,
            extra_attempts=_extra_attempts(scratch),
        )
        if verdict == "retry":
            step.restarts += 1  # restarts counts the ones actually used
        stopped = [o for o in orphans if o["recovery"] in ("terminated", "killed")]
        note = f"; stopped the old process group {', '.join(sorted({str(o['pgid']) for o in stopped}))}" if stopped else ""
        if verdict == "cancelled":
            reason = "cancelled (the worker stopped before it saw the request)"
        elif verdict == "retry":
            reason = f"stale_heartbeat (restart {step.restarts}/{policy.restart_limit})"
        else:
            reason = (
                f"stale_heartbeat (no restart left: {step.restarts}/{policy.restart_limit} used, "
                f"{step.attempts} attempts)"
            )
        if attempt is not None:
            detail = {
                **(attempt.provider_metadata or {}).get("workflow_attempt", {}),
                "error": None if verdict == "cancelled" else reason + note,
                "decision": {
                    "action": verdict,
                    "reason": "cancelled" if verdict == "cancelled" else "stale_heartbeat",
                },
                "finished_at": now,
            }
            if orphans:
                detail["processes"] = orphans
            if verdict == "cancelled":
                reason_text = (cancel or {}).get("reason")
                detail["outcome"] = {
                    "kind": "cancelled",
                    "requested_model": step.chosen_model,
                    **({"explanation": reason_text} if reason_text else {}),
                }
            attempt.provider_metadata = {
                **(attempt.provider_metadata or {}),
                "workflow_attempt": detail,
            }
            attempt.status = "failed"
            attempt.health_detail = "cancelled" if verdict == "cancelled" else "stale_heartbeat"
            await store_child_session_lifecycle_event(
                db, attempt, SessionEventType.CHILD_SESSION_RESULT
            )
        scratch["last"] = {
            "attempt": step.attempts,
            "model": step.chosen_model,
            "status": "failed",
            "reason": "cancelled" if verdict == "cancelled" else "stale_heartbeat",
            "kind": "cancelled" if verdict == "cancelled" else "crash",
            "error": None if verdict in ("retry", "cancelled") else reason + note,
            "attempt_session_id": step.current_attempt_session_id,
        }
        if verdict == "retry":
            # A crash is not the model's refusal: run the same model again, from the step checkpoint.
            step.status = "pending"
            scratch.update(pinned_model=step.chosen_model, reset_on_next=True, hop=None)
        elif verdict == "cancelled":
            step.status = "cancelled"
            scratch.update(hop=None, pinned_model=None, cancel=cancel)
            if meta.get("cancel"):
                all_steps = await _steps(db, run_id)
                if not _others_running(all_steps, step):
                    _cancel_run(run, meta, all_steps, meta["cancel"], now)
        else:
            step.status = "failed"
        step.outcome = scratch
        await db.commit()
        return _meta(run)["state"] == "running"


async def _resume_if_due(run_id: str, deps: EngineDeps, now: float) -> bool:
    async with deps.factory()() as db:
        run = await _lock_run(db, run_id)
        if run is None:
            return False
        meta = _meta(run)
        policy = load_policy(meta["policy"])
        pause = meta.get("pause") or {}
        if meta.get("state") == "needs_owner" and pause.get("reason") == "usage_limit_wait":
            if pause.get("resume_after") and pause["resume_after"] <= now:
                for step in await _steps(db, run_id):
                    if step.status == "needs_owner":
                        step.status = "pending"
                _set_meta(run, {**meta, "state": "running", "pause": None}, now=now)
                await db.commit()
                return True
            return False
        if meta.get("state") != "running":
            return False
        steps = await _steps(db, run_id)
        idle = now - (run.last_activity_at.timestamp() if run.last_activity_at else 0.0)
        if not any(s.status == "running" for s in steps) and idle >= policy.stale_after_seconds:
            return any(s.status == "pending" for s in steps) or all(
                s.status in TERMINAL_STEP for s in steps
            )
        return False


# --- owner resume ------------------------------------------------------------------------------------


async def resume_run(
    db: AsyncSession,
    run_id: str,
    decision: OwnerDecision,
    *,
    requested_by: str | None = None,
    request_source: str | None = None,
    deps: EngineDeps | None = None,
) -> dict[str, Any]:
    deps = deps or EngineDeps()
    now = deps.clock()
    run = await _lock_run(db, run_id)
    if run is None:
        raise WorkflowRunError("not_found", "run not found")
    meta = _meta(run)
    if meta.get("state") != "needs_owner":
        raise WorkflowRunError(
            "not_paused", f"run is {meta.get('state')}, not waiting for the owner"
        )
    if (meta.get("pause") or {}).get("reason") == "blocked_dependencies":
        raise WorkflowRunError(
            "blocked_dependencies",
            "the run is blocked on dependencies, not on a step decision; revise the plan "
            "(change a step's depends_on or remove the blocked steps), or cancel the run",
            blocked=(meta.get("pause") or {}).get("blocked"),
        )
    steps = await _steps(db, run_id)
    key = decision.step_key or (meta.get("pause") or {}).get("step_key")
    # A step the owner is asked about waits as needs_owner; when the run waits because steps failed, those are the ones.
    waiting = ("failed", "refused") if (meta.get("pause") or {}).get("reason") == "step_failed" else ("needs_owner",)
    step = next((s for s in steps if s.step_key == key and s.status in waiting), None)
    if step is None:
        raise WorkflowRunError(
            "no_such_step", f"no step waiting for the owner{f' named {key}' if key else ''}"
        )
    scratch = _scratch(step)
    scratch["owner_decision"] = {
        "action": decision.action,
        "model": decision.model,
        "note": decision.note,
        "extra_attempts": decision.extra_attempts,
        "at": now,
    }
    category = (meta.get("pause") or {}).get("category")
    if decision.action == "retry":
        # A fresh pass over the agent's chain (or the model the owner names); the worktree is kept.
        if decision.extra_attempts:
            # An explicit, recorded raise of this step's cap; only the owner can ask for it.
            earlier: list[dict[str, Any]] = list((scratch.get("extra_attempts") or {}).get("grants", []))
            scratch["extra_attempts"] = {
                "total": _extra_attempts(scratch) + decision.extra_attempts,
                "grants": [
                    *earlier,
                    {
                        "count": decision.extra_attempts,
                        "requested_by": requested_by,
                        "request_source": request_source,
                        "requested_at": now,
                        "note": decision.note,
                    },
                ],
            }
        cap = attempts_exhausted(
            step.attempts,
            step.definition.get("max_attempts"),
            load_policy(meta["policy"]),
            _extra_attempts(scratch),
        )
        if cap:
            raise WorkflowRunError(
                "attempt_limit",
                f"step {step.step_key} has used its attempts ({step.attempts}, {cap}); "
                "resume with extra_attempts to allow more, skip it or end the run",
            )
        refusals = {k: v for k, v in meta.get("refusals", {}).items() if k != category}
        scratch.update(
            tried=[],
            usage_limited=[],
            pinned_model=decision.model,
            hop=None,
            usage_limit_resumes=0,
            unproductive_resumes=0,
            work_at_resume=scratch.get("work_total", 0),
            acceptance_failures=0,
        )
        scratch.pop("acceptance_note", None)
        step.status, step.outcome = "pending", scratch
        _set_meta(run, {**meta, "state": "running", "pause": None, "refusals": refusals}, now=now)
    elif decision.action == "skip":
        step.status, step.outcome = "skipped", scratch
        _set_meta(run, {**meta, "state": "running", "pause": None}, now=now)
    else:
        refused = step.status == "refused" or (scratch.get("last") or {}).get("kind") == "refused"
        step.status, step.outcome = ("refused" if refused else "failed"), scratch
        _fail_run(run, meta, steps, f"{step.step_key}: owner ended the run", now)
    await db.commit()
    return {
        "run_id": run_id,
        "state": _meta(run)["state"],
        "step": step.step_key,
        "status": step.status,
    }


# --- cancel ------------------------------------------------------------------------------------------


def _cancel_record(
    request: CancelRequest, scope: str, requested_by: str | None, request_source: str | None, now: float
) -> dict[str, Any]:
    return {
        "scope": scope,
        "reason": request.reason,
        "requested_by": requested_by,
        "request_source": request_source,
        "requested_at": now,
    }


async def cancel_run(
    db: AsyncSession,
    run_id: str,
    request: CancelRequest,
    *,
    requested_by: str | None = None,
    request_source: str | None = None,
    deps: EngineDeps | None = None,
) -> dict[str, Any]:
    """Stop the whole run.

    The request is a durable flag. With no step running the run ends as cancelled at once (pending steps skipped);
    with a step running the worker that owns it sees the flag within a heartbeat, stops the step's processes and
    ends the run. Asking again while that is under way returns the same state.
    """

    deps = deps or EngineDeps()
    now = deps.clock()
    run = await _lock_run(db, run_id)
    if run is None:
        raise WorkflowRunError("not_found", "run not found")
    meta = _meta(run)
    state = meta.get("state")
    if state in FINISHED_RUN:
        raise WorkflowRunError("already_finished", f"run is already {state}", state=state)
    steps = await _steps(db, run_id)
    if meta.get("cancel") is None:
        cancel = _cancel_record(request, "run", requested_by, request_source, now)
        if any(s.status == "running" for s in steps):
            _set_meta(run, {**meta, "cancel": cancel}, now=now)
        else:
            _cancel_run(run, meta, steps, cancel, now)
        await db.commit()
    meta = _meta(run)
    return {
        "run_id": run_id,
        "state": meta["state"],
        "cancel": meta["cancel"],
        "cancelling": meta["state"] == "running",
    }


async def cancel_step(
    db: AsyncSession,
    run_id: str,
    step_key: str,
    request: CancelRequest,
    *,
    requested_by: str | None = None,
    request_source: str | None = None,
    deps: EngineDeps | None = None,
) -> dict[str, Any]:
    """Stop one step; the run carries on with its other steps, as it does after an owner skip.

    A running step is flagged and stopped by the worker that owns it; a step that has not started (or waits for
    the owner) is cancelled at once and never runs.
    """

    deps = deps or EngineDeps()
    now = deps.clock()
    run = await _lock_run(db, run_id)
    if run is None:
        raise WorkflowRunError("not_found", "run not found")
    meta = _meta(run)
    state = meta.get("state")
    if state in FINISHED_RUN:
        raise WorkflowRunError("already_finished", f"run is already {state}", state=state)
    step = next((s for s in await _steps(db, run_id) if s.step_key == step_key), None)
    if step is None:
        raise WorkflowRunError("step_not_found", f"run has no step named {step_key}")
    if step.status in FINISHED_STEP:
        raise WorkflowRunError(
            "already_finished",
            f"step {step_key} is already {step.status}",
            state=state,
            step_status=step.status,
        )
    scratch = _scratch(step)
    if scratch.get("cancel") is None:
        scratch["cancel"] = _cancel_record(request, "step", requested_by, request_source, now)
        if step.status != "running":
            step.status = "cancelled"
            if state == "needs_owner" and (meta.get("pause") or {}).get("step_key") == step_key:
                _set_meta(run, {**meta, "state": "running", "pause": None}, now=now)
        step.outcome = scratch
        await db.commit()
    return {
        "run_id": run_id,
        "state": _meta(run)["state"],
        "step": step_key,
        "status": step.status,
        "cancel": scratch["cancel"],
        "cancelling": step.status == "running",
    }


# --- views -----------------------------------------------------------------------------------------


def _limits(policy: RunPolicy) -> dict[str, int]:
    """The caps the runner enforces, for the run page's "n of N"."""

    return {
        key: getattr(policy, key)
        for key in (
            "max_total_attempts",
            "max_unproductive_usage_limit_resumes",
            "acceptance_retry_limit",
            "restart_limit",
            "refusal_pause_threshold",
        )
    }


def _workspace_view(
    step: WorkflowStep, history: list[dict[str, Any]], meta: dict[str, Any]
) -> dict[str, Any] | None:
    """Where the step works or worked: its lane (worktree, branch, base commit, merge result), or the run's worktree."""

    record = _scratch(step).get("workspace") or next(
        (a["workspace"] for a in reversed(history) if a.get("workspace")), None
    )
    if not record:
        return None
    return {**record, "kind": "lane" if record.get("lane") else "run"}


def _result_view(meta: dict[str, Any], steps: list[WorkflowStep]) -> dict[str, Any] | None:
    """Where the run's code is: the run branch and worktree. A run on lanes has it once it completes."""

    if meta.get("parallel"):
        return {**meta["result"], "mode": "lanes"} if meta.get("result") else None
    return {
        "mode": "run_worktree",
        "state": "complete" if meta.get("state") == "completed" else None,
        "branch": meta.get("branch"),
        "worktree": meta.get("worktree"),
        "sha": _start_sha(steps, meta) if meta.get("repo_path") else None,
    }


async def get_run_view(db: AsyncSession, run_id: str) -> dict[str, Any] | None:
    run = (
        await db.execute(
            select(Session).where(Session.id == run_id, Session.session_type == "workflow")
        )
    ).scalar_one_or_none()
    if run is None:
        return None
    meta = _meta(run)
    policy = load_policy(meta["policy"])
    steps = await _steps(db, run_id)
    plan = schedule(steps)
    children = (
        (
            await db.execute(
                select(Session)
                .where(Session.parent_session_id == run_id)
                .order_by(Session.created_at, Session.id)
            )
        )
        .scalars()
        .all()
    )
    attempts: dict[str, list[dict[str, Any]]] = {}
    live: dict[str, dict[str, Any]] = {}
    for child in children:
        pm = child.provider_metadata or {}
        shown = (pm.get("live_activity") or {}).get("workflow")
        if isinstance(shown, dict) and child.status == "active":
            live[child.id] = {
                "phase": shown.get("phase"),
                "last_event_at": _iso(shown.get("last_event_at")),
                "harness_pid": shown.get("harness_pid"),
                "harness_alive": shown.get("harness_alive"),
                "updated_at": _iso(shown.get("updated_at")),
            }
        detail = pm.get("workflow_attempt")
        if not detail:
            continue
        attempts.setdefault(detail["step_key"], []).append(
            {
                "session_id": child.id,
                "attempt": detail["attempt"],
                "status": child.status,
                # Same keys the session UI reads for requested vs actual model.
                "requested_model": pm.get("requested_model"),
                "effective_model": pm.get("effective_model"),
                # Stored only when the answering model differs from the one asked for; a finished attempt otherwise
                # was answered by the last model the executor reported. One that never finished had no answer.
                "served_model": pm.get("served_model")
                or ((detail.get("served_models") or [None])[-1] if child.status == "completed" else None),
                "fallback_used": pm.get("fallback_used"),
                "fallback_reason": pm.get("fallback_reason"),
                "served_models": detail.get("served_models") or [],
                # What the executor reported before it was mapped to catalog ids; null when it already was one.
                "served_reported": detail.get("served_reported"),
                "tools": detail.get("tools"),
                "hop_from": detail.get("hop"),
                "next_hop": detail.get("next_hop"),
                "outcome": detail.get("outcome"),
                "usage": detail.get("usage"),
                "cost": _attempt_cost(detail.get("usage")),
                "error": detail.get("error"),
                "decision": detail.get("decision"),
                "native_session_id": detail.get("native_session_id"),
                "transcript_path": detail.get("transcript_path"),
                "context_status": detail.get("context_status"),
                "acceptance": detail.get("acceptance"),
                "executor": detail.get("executor"),
                "processes": [
                    {k: p.get(k) for k in ("kind", "pid", "pgid", "recovery")}
                    for p in detail.get("processes") or []
                ],
                "workspace": detail.get("workspace"),
                "started_at": child.created_at.isoformat() if child.created_at else None,
                "finished_at": _iso(detail.get("finished_at")),
            }
        )
    for history in attempts.values():
        history.sort(key=lambda item: item["attempt"])
    return {
        "id": run.id,
        "state": meta.get("state"),
        "goal": meta.get("goal"),
        "project_id": run.project_id,
        "task_id": meta.get("task_id"),
        "repo_path": meta.get("repo_path"),
        "branch": meta.get("branch"),
        "base_sha": meta.get("base_sha"),
        "worktree": meta.get("worktree"),
        "run_dir": meta.get("run_dir"),
        "pause": meta.get("pause"),
        "failure": meta.get("failure"),
        "cancel": meta.get("cancel"),
        "cancelling": meta.get("state") == "running" and meta.get("cancel") is not None,
        "refusals": meta.get("refusals", {}),
        "launched_by": meta.get("launched_by"),
        "coordinator": meta.get("coordinator"),
        "plan_revision": meta.get("plan_revision", 0),
        "plan_history": meta.get("plan_history", []),
        "limits": _limits(policy),
        "max_concurrent_steps": policy.max_concurrent_steps,
        "running_steps": [s.step_key for s in steps if s.status == "running"],
        "uses_lanes": bool(meta.get("parallel")),
        "result": _result_view(meta, steps),
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "last_activity_at": run.last_activity_at.isoformat() if run.last_activity_at else None,
        "usage_totals": usage_totals(
            (item["usage"] or {}) for history in attempts.values() for item in history
        ),
        "steps": [
            {
                "key": s.step_key,
                "position": s.position,
                "status": s.status,
                "agent_slug": s.definition["agent_slug"],
                "chain": _scratch(s).get("chain"),
                "depends_on": plan.deps[s.step_key],
                "depends_on_explicit": s.definition.get("depends_on") is not None,
                "readiness": plan.readiness[s.step_key].as_dict() if s.step_key in plan.readiness else None,
                "attempts": s.attempts,
                "attempt_limit": attempt_limit(
                    s.definition.get("max_attempts"), policy, _extra_attempts(_scratch(s))
                ),
                "extra_attempts": _scratch(s).get("extra_attempts"),
                "restarts": s.restarts,
                "usage_limit_resumes": _scratch(s).get("usage_limit_resumes", 0),
                "unproductive_resumes": _unproductive_resumes(_scratch(s)),
                "acceptance_failures": _scratch(s).get("acceptance_failures", 0),
                "acceptance": acceptance_runner.commands_of(s.definition),
                "effort": s.definition.get("effort"),
                "chosen_model": s.chosen_model,
                "answered_by": (_scratch(s).get("last") or {}).get("served_models"),
                "hops": _scratch(s).get("hops", []),
                "checkpoint_sha": s.checkpoint_sha,
                "workspace": _workspace_view(s, attempts.get(s.step_key, []), meta),
                "handoff": s.handoff,
                "outcome": _scratch(s).get("last"),
                "owner_decision": _scratch(s).get("owner_decision"),
                "cancel": _scratch(s).get("cancel"),
                "cancelling": s.status == "running" and _scratch(s).get("cancel") is not None,
                "heartbeat_at": s.heartbeat_at.isoformat() if s.heartbeat_at else None,
                "live": live.get(s.current_attempt_session_id) if s.status == "running" else None,
                "attempt_history": attempts.get(s.step_key, []),
            }
            for s in steps
        ],
    }
