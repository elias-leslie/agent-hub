"""Step policy: pure decisions about which model runs a step attempt and what an outcome means.

The ordered model chain of a step is the route of its agent (primary, fallbacks, escalation), resolved
by the engine from Agent Hub's agent routing; nothing here names a model. Availability (inactive model,
missing credential, provider cooldown) is computed by the engine with the shared routing helpers and
passed in. Provider outcomes come from ``app.llm.utils.outcomes``.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

from app.llm.utils.outcomes import ProviderOutcome

DEFAULTS_FILE = Path(__file__).with_name("policy_defaults.json")

# Keys runs stored (or callers sent) before they were removed or renamed; dropped on load so old runs still open.
RETIRED_KEYS = frozenset({"acceptance_timeout_seconds", "max_usage_limit_resumes"})
# Keys of the worker, not of a run: stored with every run's policy for display, but the data file always decides.
WORKER_KEYS = frozenset({"advance_task_execution_timeout_hours", "advance_task_schedule_timeout_hours"})


@dataclass(frozen=True)
class RunPolicy:
    # Steps that may run at once. The scheduler starts every ready step up to this many; 1 runs the plan one step at a
    # time in the run's own worktree, more gives each running step a worktree of its own (see workspace.py).
    max_concurrent_steps: int
    # How much the run's steps may do with tools, for every executor the same way: "read" (look only), "lean" (the
    # core read, edit, write and shell tools) or "full" (the harness's whole tool set). The coordinator sets it when
    # the run is created; a step's own ``level`` can only narrow it. The levels and their order are data
    # (executor_defaults.json ``tool_levels``, narrowest first); each executor maps a level to its own tool list.
    tool_level: str
    # Restarts a step may use after a stalled attempt (the step fails when it stalls again past this many).
    restart_limit: int
    stale_after_seconds: int
    heartbeat_interval_seconds: float
    # Refused/substituted attempts per category across a run before it pauses for the owner. Every refusal
    # that hops to the next chain model counts, so the default is far above a normal takeover.
    refusal_pause_threshold: int
    # Hard cap on attempts of one step on every path: errors, refusals, substitutions, usage-limit cycles,
    # acceptance retries, restarts and owner retries. A step's own ``max_attempts`` may lower it.
    max_total_attempts: int
    # Consecutive usage-limit waits after which the step made no progress (no new tokens since the previous resume)
    # before it pauses for the owner instead. A wait that follows progress resets the count: waiting costs nothing,
    # a loop that never gets anywhere is the failure.
    max_unproductive_usage_limit_resumes: int
    # Retries of a step whose acceptance commands failed, before the step fails.
    acceptance_retry_limit: int
    acceptance_output_tail_chars: int
    # How long a finished or killed acceptance command's output is read for, so an escaped grandchild that still
    # holds the pipe cannot hold the step up.
    acceptance_drain_seconds: float
    # Cancel, recovery of an orphan and cleanup of an attempt's processes: SIGTERM to the process group, SIGKILL
    # after this many seconds.
    process_stop_grace_seconds: float
    usage_limit_cooldown_seconds: int
    # Hatchet cancels a task at its execution deadline and cannot be given none (the engine accepts at most ~292 years),
    # so the advance task that runs a whole attempt gets a deadline far beyond any attempt: ~100 years. These are read
    # once when the worker registers the task (workflow_run.py), so they are the worker's, not a run's: a run's own
    # override is ignored. They are shown here so the run's policy names every time bound on it. A run killed by
    # one would have no heartbeat after it; recovery charges it as a stale step.
    advance_task_execution_timeout_hours: int
    advance_task_schedule_timeout_hours: int
    packet_budget_fraction: float
    default_context_window: int
    # Executor kind for a model by provider, when a step does not name one.
    executor_for_provider: dict[str, str]
    context: dict[str, str]
    git: dict[str, str]

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def load_policy(
    overrides: Mapping[str, Any] | None = None, *, path: Path = DEFAULTS_FILE
) -> RunPolicy:
    """Defaults from the data file, with a run's own ``policy`` overrides merged over them."""

    data: dict[str, Any] = json.loads(path.read_text())
    overrides = {k: v for k, v in (overrides or {}).items() if k not in RETIRED_KEYS | WORKER_KEYS}
    unknown = set(overrides) - set(data)
    if unknown:
        raise ValueError(f"unknown policy keys: {sorted(unknown)}")
    for key, value in overrides.items():
        data[key] = {**data[key], **value} if isinstance(data[key], dict) else value
    cap = data["max_concurrent_steps"]
    if not isinstance(cap, int) or isinstance(cap, bool) or cap < 1:
        raise ValueError("max_concurrent_steps must be a whole number of at least 1")
    if data["tool_level"] not in tool_levels():
        raise ValueError(f"tool_level must be one of {tool_levels()}")
    return RunPolicy(**data)


def tool_levels() -> list[str]:
    """The tool levels, narrowest first (executor_defaults.json)."""

    from .executor_common import load_defaults

    return list(load_defaults()["tool_levels"])


def effective_tool_level(run_level: str, step_level: str | None) -> str:
    """The level a step runs at: its own when narrower than the run's, else the run's (a step never widens the run)."""

    order = tool_levels()
    if step_level is None or step_level not in order:
        return run_level
    return min(run_level, step_level, key=order.index)


def require_level_within_run(policy: RunPolicy, step: Mapping[str, Any]) -> None:
    """Refuse a step that asks for a wider tool level than its run allows."""

    order = tool_levels()
    wanted = step.get("level")
    if wanted in order and order.index(wanted) > order.index(policy.tool_level):
        raise ValueError(
            f"step {step.get('key')!r} asks for tool level {wanted!r}, wider than the run's {policy.tool_level!r}; "
            "set the run's tool level (policy.tool_level) when creating it"
        )


# An executor that cannot give the step the tools it needs ends the attempt with an error starting with this word.
# Like an unavailable model, it moves the step to the next chain entry; with none left the run waits for the owner.
TOOLS_UNAVAILABLE = "tools_unavailable"


@dataclass(frozen=True)
class Unavailable:
    reason: str
    # Seconds until the model may work again (provider cooldown); None when it will not recover on its own.
    retry_after: float | None = None


@dataclass(frozen=True)
class StepState:
    chain: tuple[str, ...]  # ordered models of the step's agent route
    tried: tuple[
        str, ...
    ] = ()  # models whose attempt on this step ended; each is used at most once
    attempts: int = 0
    max_attempts: int | None = None
    pinned_model: str | None = None  # restart or owner pin: run this model next
    # Tried models whose attempt ended on a usage limit; their reset still counts as a way forward.
    usage_limited: tuple[str, ...] = ()
    # Consecutive waits out of a usage limit after which the step still had no progress (the engine has already
    # reset it to 0 when the attempt just ended did make progress), and acceptance failures the step has used.
    unproductive_resumes: int = 0
    acceptance_failures: int = 0
    # Attempts the owner granted past the cap (``resume`` with ``extra_attempts``).
    extra_attempts: int = 0


@dataclass(frozen=True)
class RunState:
    refusals: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelChoice:
    model: str | None
    # Every untried model is on a provider cooldown until this unix time (the run can wait and resume).
    wait_until: float | None = None
    exhausted: bool = False


def choose_attempt_model(
    step: StepState, unavailable: Mapping[str, Unavailable], now: float, *, after: str | None = None
) -> ModelChoice:
    """First untried chain model that can be called; a pinned model is used as-is."""

    if step.pinned_model:
        return ModelChoice(step.pinned_model)
    tried = {*step.tried, *([after] if after else [])}
    remaining = [m for m in step.chain if m not in tried]
    if not remaining and not step.usage_limited:
        return ModelChoice(None, exhausted=True)
    waits: list[float] = []
    hard_blocked = False
    for model in remaining:
        blocked = unavailable.get(model)
        if blocked is None:
            return ModelChoice(model)
        if blocked.retry_after is None:
            hard_blocked = True
        else:
            waits.append(now + blocked.retry_after)
    # Models that already ran into a usage limit come back at their reset; refused or failed ones do not.
    for model in step.usage_limited:
        blocked = unavailable.get(model)
        if blocked is not None and blocked.retry_after is not None:
            waits.append(now + blocked.retry_after)
    if waits and not hard_blocked:
        return ModelChoice(None, wait_until=min(waits))
    return ModelChoice(None, exhausted=True)


@dataclass(frozen=True)
class AttemptResult:
    status: Literal["completed", "failed"]
    outcome: ProviderOutcome | None = None
    has_handoff: bool = False
    error: str | None = None
    # The step's acceptance commands: None when it has none (or they did not run), else whether all passed.
    acceptance_passed: bool | None = None
    # The owner or a coordinator asked for the step (or the whole run) to stop.
    cancelled: bool = False


@dataclass(frozen=True)
class Decision:
    action: Literal["complete", "retry", "fail", "needs_owner", "cancelled"]
    reason: str
    kind: str | None = None  # refused | substituted | usage_limit | error | acceptance | cancelled
    category: str | None = None
    next_model: str | None = None
    wait_until: float | None = None
    # {"from_model", "to_model", "category", "kind"}: the step moves to the next chain model.
    hop: dict[str, Any] | None = None
    refusals: dict[str, int] = field(default_factory=dict)


def _hop(model: str, target: str, kind: str, category: str | None) -> dict[str, Any]:
    return {"from_model": model, "to_model": target, "category": category, "kind": kind}


def usage_limit_cooldown(outcome: ProviderOutcome, policy: RunPolicy, now: float) -> float:
    """Seconds a provider stays skipped after a usage limit (until its reset, like a rate-limit cooldown)."""

    if outcome.resets_at:
        return max(outcome.resets_at - now, 1.0)
    return float(policy.usage_limit_cooldown_seconds)


def _move_on(
    model: str,
    kind: str,
    category: str | None,
    reason: str,
    step: StepState,
    unavailable: Mapping[str, Unavailable],
    now: float,
    refusals: dict[str, int],
    policy: RunPolicy,
) -> Decision:
    choice = choose_attempt_model(
        replace_tried(step, model, usage_limited=kind == "usage_limit"), unavailable, now
    )
    common = {"kind": kind, "category": category, "refusals": refusals}
    if choice.model is not None:
        return Decision(
            "retry",
            reason,
            next_model=choice.model,
            hop=_hop(model, choice.model, kind, category),
            **common,
        )
    paused = pause_reason(choice, step, policy)
    if paused == "chain_exhausted" and reason.startswith(TOOLS_UNAVAILABLE):
        paused = TOOLS_UNAVAILABLE
    reason = paused
    return Decision(
        "needs_owner",
        reason,
        wait_until=choice.wait_until if reason == "usage_limit_wait" else None,
        **common,
    )


def pause_reason(choice: ModelChoice, step: StepState, policy: RunPolicy) -> str:
    """Why a step with no model to run now waits for the owner or for a usage-limit reset.

    A wait for a reset resumes by itself; only waits that follow no progress count, and after
    ``max_unproductive_usage_limit_resumes`` of them in a row the owner decides.
    """

    if choice.wait_until is None:
        return "chain_exhausted"
    if step.unproductive_resumes >= policy.max_unproductive_usage_limit_resumes:
        return "usage_limit_resume_limit"
    return "usage_limit_wait"


def replace_tried(step: StepState, model: str, *, usage_limited: bool = False) -> StepState:
    return replace(
        step,
        tried=(*step.tried, model),
        pinned_model=None,
        usage_limited=(*step.usage_limited, model) if usage_limited else step.usage_limited,
    )


def attempt_limit(max_attempts: int | None, policy: RunPolicy, extra_attempts: int = 0) -> int:
    """Attempts one step may use in all: the run policy's hard cap, lowered by the step's own ``max_attempts``,
    raised by the attempts the owner granted that step (automatic loops never grant any)."""

    return min(policy.max_total_attempts, max_attempts or policy.max_total_attempts) + extra_attempts


def attempts_exhausted(
    attempts: int, max_attempts: int | None, policy: RunPolicy, extra_attempts: int = 0
) -> str | None:
    """The cap that forbids another attempt of a step that already ran ``attempts``, else None."""

    if attempts < attempt_limit(max_attempts, policy, extra_attempts):
        return None
    return "max_attempts" if max_attempts and max_attempts < policy.max_total_attempts else "max_total_attempts"


def decide_after_attempt(
    *,
    model: str,
    result: AttemptResult,
    step: StepState,
    run: RunState,
    policy: RunPolicy,
    owner_only_categories: Collection[str],
    unavailable: Mapping[str, Unavailable],
    now: float,
) -> Decision:
    """What a finished attempt means for the step.

    ``unavailable`` is computed after the outcome was applied: a usage limit has already put the model's
    provider on cooldown (see ``usage_limit_cooldown``). Any decision that would start another attempt
    fails the step instead once an attempt cap is reached (``attempts_exhausted``).
    """

    decision = _decide(
        model, result, step, run, policy, owner_only_categories, unavailable, now
    )
    if decision.action == "retry":
        cap = attempts_exhausted(step.attempts, step.max_attempts, policy, step.extra_attempts)
        if cap:
            return replace(decision, action="fail", reason=f"{cap}: {decision.reason}", next_model=None, hop=None)
    return decision


def _acceptance_decision(
    model: str,
    step: StepState,
    policy: RunPolicy,
    refusals: dict[str, int],
    outcome: ProviderOutcome | None,
    unavailable: Mapping[str, Unavailable],
    now: float,
) -> Decision:
    """The step's work is done by its own account but an acceptance command failed: the requested model, once more.

    ``model`` is the model the attempt was sent to, also when another one answered it (a substitution): the retry
    goes back to it while it is still eligible, and takes the next chain model only when it is not.
    """

    category = outcome.category if outcome else None
    if step.acceptance_failures >= policy.acceptance_retry_limit:
        return Decision("fail", "acceptance_retry_limit", kind="acceptance", category=category, refusals=refusals)
    if model in unavailable:
        return _move_on(model, "acceptance", category, "acceptance_failed", step, unavailable, now, refusals, policy)
    return Decision(
        "retry", "acceptance_failed", kind="acceptance", category=category, next_model=model, refusals=refusals
    )


def _decide(
    model: str,
    result: AttemptResult,
    step: StepState,
    run: RunState,
    policy: RunPolicy,
    owner_only_categories: Collection[str],
    unavailable: Mapping[str, Unavailable],
    now: float,
) -> Decision:
    refusals = dict(run.refusals)
    if result.cancelled:  # a stop request ends the attempt whatever it produced; it never moves to the next model
        return Decision("cancelled", "cancelled", kind="cancelled", refusals=refusals)
    outcome = result.outcome
    finished = result.status == "completed" and result.has_handoff
    acceptance_failed = finished and result.acceptance_passed is False

    if outcome is not None and outcome.kind == "usage_limit":
        return _move_on(
            model, "usage_limit", None, "usage_limit", step, unavailable, now, refusals, policy
        )

    if outcome is not None and outcome.kind in ("refused", "substituted"):
        category = outcome.category
        if category and category in owner_only_categories:
            return Decision(
                "needs_owner",
                "owner_only_category",
                kind=outcome.kind,
                category=category,
                refusals=refusals,
            )
        if category:
            refusals[category] = refusals.get(category, 0) + 1
            if refusals[category] >= policy.refusal_pause_threshold:
                return Decision(
                    "needs_owner",
                    "refusal_threshold",
                    kind=outcome.kind,
                    category=category,
                    refusals=refusals,
                )
        upcoming = choose_attempt_model(replace_tried(step, model), unavailable, now).model
        if finished and upcoming and outcome.served_model == upcoming:
            # The provider already ran the model the takeover would use.
            if acceptance_failed:
                return _acceptance_decision(model, step, policy, refusals, outcome, unavailable, now)
            return Decision(
                "complete",
                "substituted_to_chain_model",
                kind=outcome.kind,
                category=category,
                refusals=refusals,
            )
        return _move_on(
            model, outcome.kind, category, outcome.kind, step, unavailable, now, refusals, policy
        )

    if finished:
        if acceptance_failed:
            return _acceptance_decision(model, step, policy, refusals, None, unavailable, now)
        return Decision("complete", "completed", refusals=refusals)

    reason = "missing_handoff" if result.status == "completed" else (result.error or "error")
    return _move_on(model, "error", None, reason, step, unavailable, now, refusals, policy)


def decide_stale_step(
    *,
    restarts: int,
    attempts: int,
    max_attempts: int | None,
    policy: RunPolicy,
    cancelled: bool = False,
    extra_attempts: int = 0,
) -> Literal["retry", "fail", "cancelled"]:
    """A running step with a stale heartbeat restarts while it has used fewer than ``restart_limit`` restarts.

    ``restarts`` counts the restarts already used, not including this one. A step someone asked to stop is
    cancelled instead of restarted.
    """

    if cancelled:
        return "cancelled"
    if restarts >= policy.restart_limit or attempts_exhausted(attempts, max_attempts, policy, extra_attempts):
        return "fail"
    return "retry"
