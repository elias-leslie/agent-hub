from app.llm.types import AssistantMessage, Usage
from app.llm.utils.outcomes import ProviderOutcome, outcome_of, record_outcome


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
