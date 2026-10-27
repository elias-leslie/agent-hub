"""Step policy: pure decisions about which model runs a step attempt and what an outcome means.

The ordered model chain of a step is the route of its agent (primary, fallbacks, escalation), resolved
by the engine from Agent Hub's agent routing; nothing here names a model. Availability (inactive model,
missing credential, provider cooldown) is computed by the engine with the shared routing helpers and
passed in. Provider outcomes come from ``app.llm.utils.outcomes``.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from app.llm.utils.outcomes import ProviderOutcome

DEFAULTS_FILE = Path(__file__).with_name("policy_defaults.json")


@dataclass(frozen=True)
class RunPolicy:
    restart_limit: int
    stale_after_seconds: int
    heartbeat_interval_seconds: float
    # Refused/substituted attempts per category across a run before it pauses for the owner. Every refusal
    # that hops to the next chain model counts, so the default is far above a normal takeover.
    refusal_pause_threshold: int
    usage_limit_cooldown_seconds: int
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
    unknown = set(overrides or {}) - set(data)
    if unknown:
        raise ValueError(f"unknown policy keys: {sorted(unknown)}")
    for key, value in (overrides or {}).items():
        data[key] = {**data[key], **value} if isinstance(data[key], dict) else value
    return RunPolicy(**data)


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
    if not remaining:
        return ModelChoice(None, exhausted=True)
    waits: list[float] = []
    for model in remaining:
        blocked = unavailable.get(model)
        if blocked is None:
            return ModelChoice(model)
        if blocked.retry_after is not None:
            waits.append(now + blocked.retry_after)
    if waits and len(waits) == len(remaining):
        return ModelChoice(None, wait_until=min(waits))
    return ModelChoice(None, exhausted=True)


@dataclass(frozen=True)
class AttemptResult:
    status: Literal["completed", "failed"]
    outcome: ProviderOutcome | None = None
    has_handoff: bool = False
    error: str | None = None


@dataclass(frozen=True)
class Decision:
    action: Literal["complete", "retry", "fail", "needs_owner"]
    reason: str
    kind: str | None = None  # refused | substituted | usage_limit | error
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
) -> Decision:
    choice = choose_attempt_model(replace_tried(step, model), unavailable, now)
    common = {"kind": kind, "category": category, "refusals": refusals}
    if choice.model is not None:
        return Decision(
            "retry",
            reason,
            next_model=choice.model,
            hop=_hop(model, choice.model, kind, category),
            **common,
        )
    if choice.wait_until is not None:
        return Decision("needs_owner", "usage_limit_wait", wait_until=choice.wait_until, **common)
    return Decision("needs_owner", "chain_exhausted", **common)


def replace_tried(step: StepState, model: str) -> StepState:
    return StepState(step.chain, (*step.tried, model), step.attempts, step.max_attempts)


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
    provider on cooldown (see ``usage_limit_cooldown``).
    """

    refusals = dict(run.refusals)
    outcome = result.outcome

    if outcome is not None and outcome.kind == "usage_limit":
        return _move_on(model, "usage_limit", None, "usage_limit", step, unavailable, now, refusals)

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
        if (
            result.status == "completed"
            and result.has_handoff
            and upcoming
            and outcome.served_model == upcoming
        ):
            # The provider already ran the model the takeover would use.
            return Decision(
                "complete",
                "substituted_to_chain_model",
                kind=outcome.kind,
                category=category,
                refusals=refusals,
            )
        return _move_on(
            model, outcome.kind, category, outcome.kind, step, unavailable, now, refusals
        )

    if result.status == "completed" and result.has_handoff:
        return Decision("complete", "completed", refusals=refusals)

    reason = "missing_handoff" if result.status == "completed" else (result.error or "error")
    if step.max_attempts is not None and step.attempts >= step.max_attempts:
        return Decision("fail", f"max_attempts: {reason}", kind="error", refusals=refusals)
    return _move_on(model, "error", None, reason, step, unavailable, now, refusals)


def decide_stale_step(
    *, restarts: int, attempts: int, max_attempts: int | None, policy: RunPolicy
) -> Literal["retry", "fail"]:
    """A running step with a stale heartbeat has used a restart (already counted in ``restarts``)."""

    if restarts >= policy.restart_limit or (max_attempts is not None and attempts >= max_attempts):
        return "fail"
    return "retry"
