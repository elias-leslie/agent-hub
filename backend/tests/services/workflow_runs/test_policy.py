"""Step policy: chain progression, refusal takeover, usage limits, restarts (pure functions)."""

from __future__ import annotations

import pytest

from app.llm.utils.outcomes import ProviderOutcome
from app.services.workflow_runs.policy import (
    AttemptResult,
    RunState,
    StepState,
    Unavailable,
    choose_attempt_model,
    decide_after_attempt,
    decide_stale_step,
    load_policy,
    usage_limit_cooldown,
)

OPUS, CODEX, OPUS_OLD = "claude-opus-5-5", "codex/gpt-5.6-sol-daybreak-blue", "claude-opus-4-8"
CHAIN = (OPUS, CODEX, OPUS_OLD)
POLICY = load_policy({"refusal_pause_threshold": 3})
OWNER_ONLY = {"reasoning_extraction", "frontier_llm"}
NOW = 1_000_000.0
DONE = AttemptResult("completed", has_handoff=True)


def refused(model: str, category: str | None = "cyber") -> AttemptResult:
    return AttemptResult(
        "failed", ProviderOutcome("refused", model, category=category), error="refused"
    )


def decide(model, result, *, tried=(), refusals=None, unavailable=None, chain=CHAIN, **step_kwargs):
    return decide_after_attempt(
        model=model,
        result=result,
        step=StepState(chain, tuple(tried), **step_kwargs),
        run=RunState(refusals or {}),
        policy=POLICY,
        owner_only_categories=OWNER_ONLY,
        unavailable=unavailable or {},
        now=NOW,
    )


def test_primary_is_first_chain_model_and_each_step_starts_from_its_own_primary() -> None:
    assert choose_attempt_model(StepState(CHAIN), {}, NOW).model == OPUS
    # After a takeover on one step, the next step has no tried models and Opus returns.
    assert choose_attempt_model(StepState(CHAIN, tried=()), {}, NOW).model == OPUS


def test_refusal_hops_to_next_chain_model_across_providers() -> None:
    decision = decide(OPUS, refused(OPUS))
    assert decision.action == "retry"
    assert decision.next_model == CODEX
    assert decision.hop == {
        "from_model": OPUS,
        "to_model": CODEX,
        "category": "cyber",
        "kind": "refused",
    }
    assert decision.refusals == {"cyber": 1}


def test_second_refusal_continues_down_the_chain_and_each_model_is_tried_once() -> None:
    decision = decide(CODEX, refused(CODEX), tried=[OPUS])
    assert (decision.action, decision.next_model) == ("retry", OPUS_OLD)
    exhausted = decide(OPUS_OLD, refused(OPUS_OLD), tried=[OPUS, CODEX])
    assert (exhausted.action, exhausted.reason) == ("needs_owner", "chain_exhausted")


def test_single_model_chain_refusal_goes_to_owner() -> None:
    decision = decide(OPUS, refused(OPUS), chain=(OPUS,))
    assert (decision.action, decision.reason) == ("needs_owner", "chain_exhausted")


@pytest.mark.parametrize("category", sorted(OWNER_ONLY))
def test_owner_only_categories_never_reach_the_chain(category: str) -> None:
    decision = decide(OPUS, refused(OPUS, category))
    assert (decision.action, decision.reason, decision.next_model) == (
        "needs_owner",
        "owner_only_category",
        None,
    )


def test_refusal_threshold_pauses_the_run() -> None:
    decision = decide(OPUS, refused(OPUS), refusals={"cyber": 2})
    assert (decision.action, decision.reason) == ("needs_owner", "refusal_threshold")


def test_substitution_retries_on_next_chain_model_unless_it_already_answered_there() -> None:
    substituted = ProviderOutcome("substituted", OPUS, served_model=OPUS_OLD, category="cyber")
    retry = decide(OPUS, AttemptResult("completed", substituted, True))
    assert (retry.action, retry.next_model, retry.kind) == ("retry", CODEX, "substituted")
    served_next = ProviderOutcome("substituted", OPUS, served_model=CODEX, category="cyber")
    accepted = decide(OPUS, AttemptResult("completed", served_next, True))
    assert (accepted.action, accepted.reason) == ("complete", "substituted_to_chain_model")


def test_usage_limit_skips_the_provider_and_waits_when_nothing_else_is_left() -> None:
    limited = {CODEX: Unavailable("cooldown", 600.0), OPUS_OLD: Unavailable("cooldown", 900.0)}
    assert (
        choose_attempt_model(StepState(CHAIN), {OPUS: Unavailable("cooldown", 60.0)}, NOW).model
        == CODEX
    )
    assert (
        choose_attempt_model(StepState(CHAIN, tried=(OPUS,)), limited, NOW).wait_until
        == NOW + 600.0
    )
    result = AttemptResult(
        "failed", ProviderOutcome("usage_limit", OPUS, resets_at=int(NOW) + 300), error="limit"
    )
    decision = decide(OPUS, result, unavailable=limited)
    assert (decision.action, decision.reason, decision.wait_until) == (
        "needs_owner",
        "usage_limit_wait",
        NOW + 600.0,
    )
    moved = decide(OPUS, result, unavailable={OPUS: Unavailable("cooldown", 300.0)})
    assert (moved.action, moved.next_model, moved.hop["kind"]) == ("retry", CODEX, "usage_limit")


def test_usage_limited_models_wait_for_the_earliest_reset_instead_of_exhausting_the_chain() -> None:
    limit = AttemptResult(
        "failed", ProviderOutcome("usage_limit", CODEX, resets_at=int(NOW) + 300), error="limit"
    )
    blocked = {OPUS: Unavailable("cooldown", 900.0), CODEX: Unavailable("cooldown", 300.0)}
    both = decide(CODEX, limit, tried=[OPUS], chain=(OPUS, CODEX), unavailable=blocked,
                  usage_limited=(OPUS,))
    assert (both.action, both.reason, both.wait_until) == (
        "needs_owner",
        "usage_limit_wait",
        NOW + 300,
    )
    only = decide(OPUS, limit, chain=(OPUS,), unavailable={OPUS: Unavailable("cooldown", 60.0)})
    assert (only.reason, only.wait_until) == ("usage_limit_wait", NOW + 60)
    # A refusal in the chain, or a model that cannot recover, keeps chain_exhausted.
    refusal = decide(CODEX, refused(CODEX), tried=[OPUS], chain=(OPUS, CODEX))
    assert refusal.reason == "chain_exhausted"
    hard = decide(
        OPUS,
        limit,
        chain=(OPUS, CODEX),
        unavailable={OPUS: Unavailable("cooldown", 60.0), CODEX: Unavailable("inactive")},
    )
    assert hard.reason == "chain_exhausted"


def test_usage_limit_cooldown_runs_until_reset_or_the_policy_default() -> None:
    assert (
        usage_limit_cooldown(
            ProviderOutcome("usage_limit", OPUS, resets_at=int(NOW) + 120), POLICY, NOW
        )
        == 120
    )
    assert (
        usage_limit_cooldown(ProviderOutcome("usage_limit", OPUS), POLICY, NOW)
        == POLICY.usage_limit_cooldown_seconds
    )


def test_plain_error_moves_to_next_model_and_max_attempts_fails_the_step() -> None:
    error = AttemptResult("failed", error="boom")
    assert decide(OPUS, error).next_model == CODEX
    capped = decide(OPUS, error, attempts=2, max_attempts=2)
    assert (capped.action, capped.reason.startswith("max_attempts")) == ("fail", True)


def test_every_retrying_path_stops_at_the_total_attempt_cap() -> None:
    total = POLICY.max_total_attempts
    paths = {
        "error": AttemptResult("failed", error="boom"),
        "refusal": refused(OPUS),
        "substitution": AttemptResult(
            "completed", ProviderOutcome("substituted", OPUS, served_model=OPUS_OLD, category="cyber"), True
        ),
        "usage_limit": AttemptResult(
            "failed", ProviderOutcome("usage_limit", OPUS, resets_at=int(NOW) + 60), error="limit"
        ),
        "acceptance": AttemptResult("completed", has_handoff=True, acceptance_passed=False),
    }
    for name, result in paths.items():
        assert decide(OPUS, result, attempts=total - 1).action == "retry", name
        capped = decide(OPUS, result, attempts=total)
        assert (capped.action, capped.reason.startswith("max_total_attempts")) == ("fail", True), name
    # A step's own max_attempts can lower the cap, never raise it.
    assert decide(OPUS, paths["refusal"], attempts=2, max_attempts=2).reason.startswith("max_attempts")
    assert decide(OPUS, paths["error"], attempts=total, max_attempts=total + 5).reason.startswith(
        "max_total_attempts"
    )


def test_usage_limit_waits_resume_a_limited_number_of_times_then_the_owner_decides() -> None:
    limit = AttemptResult(
        "failed", ProviderOutcome("usage_limit", OPUS, resets_at=int(NOW) + 300), error="limit"
    )
    blocked = {OPUS: Unavailable("cooldown", 300.0)}
    chain = (OPUS,)
    waiting = decide(OPUS, limit, chain=chain, unavailable=blocked, usage_limit_resumes=POLICY.max_usage_limit_resumes - 1)
    assert (waiting.reason, waiting.wait_until) == ("usage_limit_wait", NOW + 300)
    spent = decide(OPUS, limit, chain=chain, unavailable=blocked, usage_limit_resumes=POLICY.max_usage_limit_resumes)
    assert (spent.action, spent.reason, spent.wait_until) == ("needs_owner", "usage_limit_resume_limit", None)


def test_failed_acceptance_retries_the_same_model_until_the_retry_limit_then_fails() -> None:
    failed = AttemptResult("completed", has_handoff=True, acceptance_passed=False)
    passed = AttemptResult("completed", has_handoff=True, acceptance_passed=True)
    first = decide(OPUS, failed, attempts=1)
    assert (first.action, first.reason, first.kind, first.next_model, first.hop) == (
        "retry",
        "acceptance_failed",
        "acceptance",
        OPUS,
        None,
    )
    last = decide(OPUS, failed, attempts=3, acceptance_failures=POLICY.acceptance_retry_limit - 1)
    assert last.action == "retry"
    spent = decide(OPUS, failed, attempts=3, acceptance_failures=POLICY.acceptance_retry_limit)
    assert (spent.action, spent.reason) == ("fail", "acceptance_retry_limit")
    assert decide(OPUS, passed, attempts=2, acceptance_failures=1).action == "complete"
    # No acceptance commands (None) behaves as before.
    assert decide(OPUS, DONE).action == "complete"


def test_completed_without_handoff_is_an_error() -> None:
    decision = decide(OPUS, AttemptResult("completed", has_handoff=False))
    assert (decision.action, decision.reason) == ("retry", "missing_handoff")
    assert decide(OPUS, DONE).action == "complete"


def test_unavailable_chain_models_are_skipped_in_order() -> None:
    skip = {CODEX: Unavailable("no credential")}
    decision = decide(OPUS, refused(OPUS), unavailable=skip)
    assert decision.next_model == OPUS_OLD


def test_stale_step_restarts_exactly_restart_limit_times_then_fails() -> None:
    """``restarts`` is how many restarts were already used: a limit of N allows N restarts, the next stall fails."""

    limit = POLICY.restart_limit
    for used in range(limit):
        assert (
            decide_stale_step(restarts=used, attempts=1, max_attempts=None, policy=POLICY) == "retry"
        )
    assert decide_stale_step(restarts=limit, attempts=1, max_attempts=None, policy=POLICY) == "fail"
    assert decide_stale_step(restarts=0, attempts=2, max_attempts=2, policy=POLICY) == "fail"
    total = POLICY.max_total_attempts
    assert decide_stale_step(restarts=0, attempts=total, max_attempts=None, policy=POLICY) == "fail"


def test_policy_overrides_merge_and_unknown_keys_are_rejected() -> None:
    assert load_policy({"restart_limit": 5, "git": {"user_name": "x"}}).git["user_email"]
    with pytest.raises(ValueError, match="unknown policy keys"):
        load_policy({"nope": 1})
