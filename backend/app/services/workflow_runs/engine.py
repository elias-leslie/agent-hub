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
import logging
import time
import uuid
from collections.abc import Awaitable, Callable, Collection
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.utils.outcomes import outcome_details
from app.models import Session, SessionEventType, WorkflowStep
from app.services.event_storage import store_child_session_lifecycle_event
from app.services.session_live_activity import mark_session_completed

from .executors import Executor, ExecutorUnavailable, StepResult, get_executor
from .packet import AttemptRef, GitState, HandoffPacket, PriorStep, build_packet, normalize_handoff
from .policy import (
    AttemptResult,
    Decision,
    RunPolicy,
    RunState,
    StepState,
    Unavailable,
    choose_attempt_model,
    decide_after_attempt,
    decide_stale_step,
    load_policy,
    usage_limit_cooldown,
)
from .schemas import OwnerDecision, RunDefinition
from .settings import get_workflow_run_settings
from .workspace import RunWorkspace, head_sha

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
ContextProvider = Callable[..., Awaitable[tuple[str, str]]]

RUN_STATES = ("running", "needs_owner", "completed", "failed")
TERMINAL_STEP = ("completed", "skipped")


class WorkflowRunError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


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
    clock: Callable[[], float] = time.time

    def factory(self) -> SessionFactory:
        if self.session_factory is not None:
            return self.session_factory
        from app.db import async_session

        return async_session

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


def _step_state(step: WorkflowStep, chain: list[str] | None = None) -> StepState:
    scratch = _scratch(step)
    return StepState(
        chain=tuple(chain if chain is not None else scratch.get("chain", ())),
        tried=tuple(scratch.get("tried", ())),
        attempts=step.attempts,
        max_attempts=step.definition.get("max_attempts"),
        pinned_model=scratch.get("pinned_model"),
        usage_limited=tuple(scratch.get("usage_limited", ())),
    )


def _retry_after_limit(scratch: dict[str, Any]) -> None:
    """Waiting out a usage limit: the limited models may run again once the pause ends."""

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


def _pause_run(run: Session, meta: dict[str, Any], pause: dict[str, Any], now: float) -> None:
    _set_meta(run, {**meta, "state": "needs_owner", "pause": {**pause, "at": now}}, now=now)


def _describe_hop(hop: dict[str, Any]) -> str:
    category = f" ({hop['category']})" if hop.get("category") else ""
    return f"{hop['kind']}{category} on {hop['from_model']}"


# --- creation ------------------------------------------------------------------------------------


async def create_run(
    db: AsyncSession, definition: RunDefinition, *, deps: EngineDeps | None = None
) -> tuple[str, bool]:
    """Create a run and its steps. Returns (run_id, created); a repeated request_id returns the first run."""

    deps = deps or EngineDeps()
    if definition.request_id:
        existing = await _run_for_request(db, definition)
        if existing:
            return existing, False
    policy = load_policy(definition.policy)
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
        existing = await _run_for_request(db, definition)
        if existing:
            return existing, False
        raise
    return run_id, True


async def _run_for_request(db: AsyncSession, definition: RunDefinition) -> str | None:
    first = definition.steps[0].key
    return await db.scalar(
        select(WorkflowStep.run_session_id).where(
            WorkflowStep.request_id == f"{definition.request_id}:{first}"
        )
    )


# --- advance ---------------------------------------------------------------------------------------


def _start_sha(steps: list[WorkflowStep], step: WorkflowStep, meta: dict[str, Any]) -> str | None:
    done = [
        s
        for s in steps
        if s.position < step.position and s.status == "completed" and s.checkpoint_sha
    ]
    return done[-1].checkpoint_sha if done else meta.get("base_sha")


def _prior(steps: list[WorkflowStep], step: WorkflowStep) -> list[PriorStep]:
    return [
        PriorStep(
            key=s.step_key,
            position=s.position,
            status=s.status,
            model=_scratch(s).get("last", {}).get("served_model") or s.chosen_model,
            handoff=s.handoff,
            notes_path=_scratch(s).get("notes_path"),
        )
        for s in steps
        if s.position < step.position and s.status == "completed"
    ]


class _Heartbeat:
    """Keeps a running step's heartbeat fresh from a ticker and from executor events."""

    def __init__(self, deps: EngineDeps, step_id: str, attempt_id: str, interval: float) -> None:
        self.deps, self.step_id, self.attempt_id, self.interval = (
            deps,
            step_id,
            attempt_id,
            interval,
        )
        self._last = deps.clock()
        self._task: asyncio.Task[None] | None = None

    async def beat(self) -> None:
        self._last = self.deps.clock()
        try:
            async with self.deps.factory()() as db:
                step = await db.get(WorkflowStep, self.step_id)
                if (
                    step is not None
                    and step.status == "running"
                    and step.current_attempt_session_id == self.attempt_id
                ):
                    step.heartbeat_at = _dt(self._last)
                    attempt = await db.get(Session, self.attempt_id)
                    if (
                        attempt is not None
                    ):  # keeps the cleanup/reaper heuristics off a live attempt
                        attempt.last_heartbeat_at = attempt.last_activity_at = _dt(self._last)
                    await db.commit()
        except Exception:
            logger.warning("workflow heartbeat failed for step %s", self.step_id, exc_info=True)

    async def on_event(self, _event: Any) -> None:
        if self.deps.clock() - self._last >= self.interval:
            await self.beat()

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(self.interval)
            await self.beat()

    async def __aenter__(self) -> _Heartbeat:
        self._task = asyncio.create_task(self._loop())
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task


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
        if any(s.status == "running" for s in steps):
            return {"next": "stop", "reason": "step_running"}, None
        step = next((s for s in steps if s.status == "pending"), None)
        if step is None:
            _complete_run(run, meta, now)
            await db.commit()
            return {"next": "stop", "reason": "completed"}, None
        scratch = _scratch(step)
        if not scratch.get("chain"):
            try:
                scratch["chain"] = await deps.resolve_chain(db, step.definition)
            except Exception as exc:
                _pause_for_step(run, step, meta, "no_agent_route", now, error=str(exc))
                await db.commit()
                return {"next": "stop", "reason": "no_agent_route"}, None
        state = _step_state(step, scratch["chain"])
        untried = [m for m in state.chain if m not in state.tried]
        unavailable = await deps.availability([*untried, *state.usage_limited])
        choice = choose_attempt_model(state, unavailable, now)
        if choice.model is None:
            reason = "usage_limit_wait" if choice.wait_until is not None else "chain_exhausted"
            if reason == "usage_limit_wait":
                _retry_after_limit(scratch)
            step.outcome = scratch
            _pause_for_step(run, step, meta, reason, now, resume_after=choice.wait_until)
            await db.commit()
            return {"next": "stop", "reason": reason, "resume_after": choice.wait_until}, None
        chain = scratch["chain"]
        provider = deps.provider_of(choice.model)
        executor = step.definition.get("executor") or RunPolicy(
            **meta["policy"]
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
            requested_model=chain[0],
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
            start_sha=_start_sha(steps, step, meta),
            meta=meta,
            prior=_prior(steps, step),
            project_id=run.project_id,
        )
        await db.commit()
    return {}, intent


async def _run_effect(intent: _Intent, deps: EngineDeps) -> tuple[StepResult, dict[str, Any]]:
    """The external effect: prepare the worktree, build the packet, run the executor."""

    meta, policy = intent.meta, RunPolicy(**intent.meta["policy"])
    identity = (f"user.name={policy.git['user_name']}", f"user.email={policy.git['user_email']}")
    workspace = RunWorkspace.from_meta(meta, identity)
    info: dict[str, Any] = {}
    try:
        await workspace.ensure()
        if intent.reset:  # restart after a crash: back to the step's checkpoint
            await workspace.reset(intent.start_sha)
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
                "partial_diff": await workspace.diff_since(intent.start_sha),
                "partial_outputs": saved.get("progress", []),
            }
        elif intent.hop:
            partial_kwargs = {
                "partial_from": intent.hop,
                "partial_diff": await workspace.diff_since(intent.start_sha),
            }
        packet: HandoffPacket = build_packet(
            run_goal=meta["goal"],
            step_key=intent.step_key,
            instructions=intent.definition["instructions"],
            acceptance=intent.definition.get("acceptance", []),
            git=git,
            prior_steps=intent.prior,
            run_dir=str(workspace.run_dir),
            context_window=window,
            budget_fraction=policy.packet_budget_fraction,
            context=context,
            retry_label=f"takeover: {_describe_hop(intent.hop)}" if intent.hop else None,
            **partial_kwargs,
        )
        packet = replace(
            packet,
            thinking_level=await deps.thinking_level_of(intent.definition["agent_slug"]),
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
    async with _Heartbeat(
        deps, intent.step_id, intent.attempt_id, policy.heartbeat_interval_seconds
    ) as heartbeat:
        try:
            result = await executor.run(
                packet, intent.model, workspace.worktree, workspace.run_dir, heartbeat.on_event
            )
        except Exception as exc:
            logger.exception("workflow step %s executor crashed", intent.step_key)
            result = StepResult("failed", error=f"executor_crashed: {exc!r}")
    return result, info


def _usage_limited(result: StepResult) -> bool:
    return result.outcome is not None and result.outcome.kind == "usage_limit"


async def advance_run(run_id: str, *, deps: EngineDeps | None = None) -> dict[str, Any]:
    """Run the next eligible step of a run. ``next`` tells the caller whether to enqueue another advance."""

    deps = deps or EngineDeps()
    early, intent = await _commit_intent(run_id, deps)
    if intent is None:
        return early
    result, info = await _run_effect(intent, deps)
    policy = RunPolicy(**intent.meta["policy"])
    identity = (f"user.name={policy.git['user_name']}", f"user.email={policy.git['user_email']}")
    workspace = RunWorkspace.from_meta(intent.meta, identity)
    handoff = normalize_handoff(result.handoff) if result.status == "completed" else None
    checkpoint: str | None = None
    notes_path: str | None = None
    partial_path: str | None = None
    if handoff is not None:
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
                f"workflow {intent.step_key}: {handoff['summary'][:60]}"
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
    )
    return await _commit_outcome(
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
        policy = RunPolicy(**meta["policy"])
        decision = decide_after_attempt(
            model=intent.model,
            result=AttemptResult(result.status, result.outcome, handoff is not None, result.error),
            step=_step_state(step),
            run=_run_state(meta),
            policy=policy,
            owner_only_categories=deps.owner_only(),
            unavailable=unavailable,
            now=now,
        )
        served = list(result.served_models) or [intent.model]
        _finish_attempt(attempt, intent, result, decision, served, info, now)
        steps = await _steps(db, run_id)
        scratch = _scratch(step)
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
        if decision.hop:
            scratch["hops"] = [*scratch.get("hops", []), decision.hop]
        if notes_path:
            scratch["notes_path"] = notes_path
        scratch["partial_path"] = partial_path
        meta = {**meta, "refusals": decision.refusals}
        step.heartbeat_at = _dt(now)
        if decision.action == "complete":
            step.status, step.handoff, step.checkpoint_sha = "completed", handoff, checkpoint
            scratch.update(hop=None, partial_path=None, pinned_model=None)
        elif decision.action == "retry":
            step.status = "pending"
            scratch.update(hop=decision.hop, pinned_model=decision.next_model)
        elif decision.action == "fail":
            step.status = "failed"
            _fail_run(run, meta, steps, f"{intent.step_key}: {decision.reason}", now)
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


def _finish_attempt(
    attempt: Session,
    intent: _Intent,
    result: StepResult,
    decision: Decision,
    served: list[str],
    info: dict[str, Any],
    now: float,
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
        requested_model=intent.chain[0],
        effective_model=intent.model,
        fallback_used=intent.model != intent.chain[0],
        fallback_reason=_describe_hop(hop) if hop else None,
        served_model=served[-1],
    )
    detail = {
        **attempt.provider_metadata.get("workflow_attempt", {}),
        "served_models": served,
        "outcome": outcome_details(result.outcome) if result.outcome else None,
        "usage": dict(result.usage),
        "error": result.error,
        "native_session_id": result.native_session_id,
        "transcript_path": result.transcript_path,
        "decision": {"action": decision.action, "reason": decision.reason},
        "next_hop": decision.hop,
        "finished_at": now,
        "context_status": info.get("context_status"),
        "packet": info.get("packet"),
        "packet_path": info.get("packet_path"),
    }
    attempt.provider_metadata = {**attempt.provider_metadata, "workflow_attempt": detail}
    attempt.models_used = list(dict.fromkeys([*(attempt.models_used or []), *served]))
    attempt.last_activity_at = _dt(now)
    served_note = f" (served {', '.join(served)})" if served != [intent.model] else ""
    ended = decision.reason if decision.action != "complete" else "completed"
    if result.error and decision.action != "complete":
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
        if await _recover_one(step_id, run_id, deps, now):
            to_advance.append(run_id)
    for run_id in runs_active:
        if run_id not in to_advance and await _resume_if_due(run_id, deps, now):
            to_advance.append(run_id)
    return to_advance


async def _recover_one(step_id: str, run_id: str, deps: EngineDeps, now: float) -> bool:
    async with deps.factory()() as db:
        run = await _lock_run(db, run_id)
        step = await db.get(WorkflowStep, step_id)
        if run is None or step is None:
            return False
        await db.refresh(step)
        meta = _meta(run)
        if step.status != "running" or meta.get("state") != "running":
            return False
        policy = RunPolicy(**meta["policy"])
        heartbeat = step.heartbeat_at.timestamp() if step.heartbeat_at else 0.0
        if now - heartbeat < policy.stale_after_seconds:
            return False
        step.restarts += 1
        verdict = decide_stale_step(
            restarts=step.restarts,
            attempts=step.attempts,
            max_attempts=step.definition.get("max_attempts"),
            policy=policy,
        )
        attempt = (
            await db.get(Session, step.current_attempt_session_id)
            if step.current_attempt_session_id
            else None
        )
        reason = f"stale_heartbeat (restart {step.restarts}/{policy.restart_limit})"
        if attempt is not None:
            detail = {
                **(attempt.provider_metadata or {}).get("workflow_attempt", {}),
                "error": reason,
                "decision": {"action": verdict, "reason": "stale_heartbeat"},
                "finished_at": now,
            }
            attempt.provider_metadata = {
                **(attempt.provider_metadata or {}),
                "workflow_attempt": detail,
            }
            attempt.status = "failed"
            attempt.health_detail = "stale_heartbeat"
            await store_child_session_lifecycle_event(
                db, attempt, SessionEventType.CHILD_SESSION_RESULT
            )
        scratch = _scratch(step)
        scratch["last"] = {
            "attempt": step.attempts,
            "model": step.chosen_model,
            "status": "failed",
            "reason": "stale_heartbeat",
            "kind": "crash",
            "attempt_session_id": step.current_attempt_session_id,
        }
        if verdict == "retry":
            # A crash is not the model's refusal: run the same model again, from the step checkpoint.
            step.status = "pending"
            scratch.update(pinned_model=step.chosen_model, reset_on_next=True, hop=None)
        else:
            step.status = "failed"
            _fail_run(run, meta, await _steps(db, run_id), f"{step.step_key}: {reason}", now)
        step.outcome = scratch
        await db.commit()
        return verdict == "retry"


async def _resume_if_due(run_id: str, deps: EngineDeps, now: float) -> bool:
    async with deps.factory()() as db:
        run = await _lock_run(db, run_id)
        if run is None:
            return False
        meta = _meta(run)
        policy = RunPolicy(**meta["policy"])
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
    db: AsyncSession, run_id: str, decision: OwnerDecision, *, deps: EngineDeps | None = None
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
    steps = await _steps(db, run_id)
    key = decision.step_key or (meta.get("pause") or {}).get("step_key")
    step = next((s for s in steps if s.step_key == key and s.status == "needs_owner"), None)
    if step is None:
        raise WorkflowRunError(
            "no_such_step", f"no step waiting for the owner{f' named {key}' if key else ''}"
        )
    scratch = _scratch(step)
    scratch["owner_decision"] = {
        "action": decision.action,
        "model": decision.model,
        "note": decision.note,
        "at": now,
    }
    category = (meta.get("pause") or {}).get("category")
    if decision.action == "retry":
        # A fresh pass over the agent's chain (or the model the owner names); the worktree is kept.
        refusals = {k: v for k, v in meta.get("refusals", {}).items() if k != category}
        scratch.update(tried=[], usage_limited=[], pinned_model=decision.model, hop=None)
        step.status, step.outcome = "pending", scratch
        _set_meta(run, {**meta, "state": "running", "pause": None, "refusals": refusals}, now=now)
    elif decision.action == "skip":
        step.status, step.outcome = "skipped", scratch
        _set_meta(run, {**meta, "state": "running", "pause": None}, now=now)
    else:
        refused = (scratch.get("last") or {}).get("kind") == "refused"
        step.status, step.outcome = ("refused" if refused else "failed"), scratch
        _fail_run(run, meta, steps, f"{step.step_key}: owner ended the run", now)
    await db.commit()
    return {
        "run_id": run_id,
        "state": _meta(run)["state"],
        "step": step.step_key,
        "status": step.status,
    }


# --- views -----------------------------------------------------------------------------------------


async def get_run_view(db: AsyncSession, run_id: str) -> dict[str, Any] | None:
    run = (
        await db.execute(
            select(Session).where(Session.id == run_id, Session.session_type == "workflow")
        )
    ).scalar_one_or_none()
    if run is None:
        return None
    meta = _meta(run)
    steps = await _steps(db, run_id)
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
    for child in children:
        pm = child.provider_metadata or {}
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
                "served_model": pm.get("served_model"),
                "fallback_used": pm.get("fallback_used"),
                "fallback_reason": pm.get("fallback_reason"),
                "served_models": detail.get("served_models") or [],
                "hop_from": detail.get("hop"),
                "next_hop": detail.get("next_hop"),
                "outcome": detail.get("outcome"),
                "usage": detail.get("usage"),
                "error": detail.get("error"),
                "decision": detail.get("decision"),
                "native_session_id": detail.get("native_session_id"),
                "transcript_path": detail.get("transcript_path"),
                "context_status": detail.get("context_status"),
                "executor": detail.get("executor"),
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
        "refusals": meta.get("refusals", {}),
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "steps": [
            {
                "key": s.step_key,
                "position": s.position,
                "status": s.status,
                "agent_slug": s.definition["agent_slug"],
                "chain": _scratch(s).get("chain"),
                "attempts": s.attempts,
                "restarts": s.restarts,
                "chosen_model": s.chosen_model,
                "answered_by": (_scratch(s).get("last") or {}).get("served_models"),
                "hops": _scratch(s).get("hops", []),
                "checkpoint_sha": s.checkpoint_sha,
                "handoff": s.handoff,
                "outcome": _scratch(s).get("last"),
                "owner_decision": _scratch(s).get("owner_decision"),
                "heartbeat_at": s.heartbeat_at.isoformat() if s.heartbeat_at else None,
                "attempt_history": attempts.get(s.step_key, []),
            }
            for s in steps
        ],
    }
