import pytest

from app.llm.types import AssistantMessage, Usage
from app.llm.utils.outcomes import ProviderOutcome, is_model_switch, outcome_of, record_outcome
from app.llm.utils.refusal_codes import codex_refusal_category, reroute_category


def _message() -> AssistantMessage:
    return AssistantMessage(
        content=[], api="claude-code-cli", provider="claude", model="claude-opus-5-5",
        usage=Usage(), stop_reason="error", timestamp=0,
    )


def test_outcome_round_trips_through_diagnostics() -> None:
    message = _message()
    outcome = ProviderOutcome(
        kind="substituted", requested_model="claude-opus-5-5", served_model="claude-opus-4-8", category="cyber",
    )
    record_outcome(message, outcome)
    assert outcome_of(message) == outcome
    assert message.diagnostics is not None
    assert message.diagnostics[0].details == {
        "kind": "substituted", "requested_model": "claude-opus-5-5",
        "served_model": "claude-opus-4-8", "category": "cyber",
    }


def test_message_without_outcome_reads_none() -> None:
    assert outcome_of(_message()) is None


@pytest.mark.parametrize(
    ("requested", "served", "switched"),
    [
        ("gpt-5.5", "gpt-5.5", False),
        ("gpt-5.5", "gpt-5.5-2026-04-23", False),
        ("claude-opus-5-5", "claude-opus-5-5-20261001", False),
        ("codex/GPT-5.5", "gpt-5.5", False),
        ("gpt-5.5", "gpt-5.4", True),
        ("claude-opus-5-5", "claude-opus-4-8", True),
        ("gpt-5.5", None, False),
        (None, "gpt-5.5", False),
    ],
)
def test_model_switch_ignores_snapshot_suffix_and_prefix(requested: str | None, served: str | None, switched: bool) -> None:
    assert is_model_switch(requested, served) is switched


@pytest.mark.parametrize(
    ("code", "category"),
    [
        ("cyberPolicy", "cyber"),
        ("cyber_policy", "cyber"),
        ("bio_policy", "bio"),
        ("misalignmentPolicyViolation", "misalignment"),
        ("misalignment_policy_violation", "misalignment"),
        ("tooManyDenials", "too_many_denials"),
        ("rateLimitExceeded", None),
        (None, None),
    ],
)
def test_codex_refusal_codes_share_one_category_map(code: str | None, category: str | None) -> None:
    assert codex_refusal_category(code) == category


def test_reroute_reason_maps_to_category_and_keeps_unknown_text() -> None:
    assert reroute_category("high_risk_cyber_activity") == "cyber"
    assert reroute_category("capacity") == "capacity"
    assert reroute_category(None) is None
