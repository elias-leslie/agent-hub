"""The one re-send policy: budget, backoff schedule and which failures count."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from app.config import settings
from app.llm.types import AssistantMessage, SimpleStreamOptions, Usage
from app.llm.utils import retry
from app.llm.utils.outcomes import outcome_of


def test_backoff_doubles_from_two_seconds_and_caps_at_sixty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(retry.random, "uniform", lambda _low, _high: 1.0)

    assert [retry.retry_delay(attempt) for attempt in range(7)] == [2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0]


def test_backoff_jitter_stays_within_the_setting() -> None:
    for attempt in range(6):
        base = min(60.0, 2.0 * 2**attempt)
        delays = [retry.retry_delay(attempt) for _ in range(50)]
        assert all(base * 0.8 <= d <= min(60.0, base * 1.2) for d in delays)


def test_backoff_values_are_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_retry_base_delay_s", 1.0)
    monkeypatch.setattr(settings, "llm_retry_max_delay_s", 3.0)
    monkeypatch.setattr(settings, "llm_retry_jitter", 0.0)

    assert [retry.retry_delay(a) for a in range(4)] == [1.0, 2.0, 3.0, 3.0]


def test_budget_defaults_to_five_and_a_request_overrides_it() -> None:
    assert retry.retry_budget(None) == settings.llm_stream_max_retries == 5
    assert retry.retry_budget(SimpleStreamOptions(max_retries=0)) == 0


class _Status(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class APIConnectionError(Exception):  # name-matched, as the Anthropic and OpenAI SDKs raise it
    pass


@pytest.mark.parametrize(
    ("exc", "transient"),
    [
        (httpx.ReadTimeout("t"), True),
        (httpx.RemoteProtocolError("closed"), True),
        (ConnectionResetError(), True),
        (APIConnectionError("down"), True),
        (_Status(500), True),
        (_Status(503), True),
        (_Status(529), True),
        (_Status(429), False),
        (_Status(400), False),
        (_Status(401), False),
        (RuntimeError("bad request"), False),
        (SimpleNamespace(code=True), False),
    ],
)
def test_only_definite_transport_and_server_failures_are_transient(exc: object, transient: bool) -> None:
    assert retry.is_transient_failure(exc) is transient


def test_a_transient_failure_is_tagged_interrupted_and_others_are_not() -> None:
    def failed() -> AssistantMessage:
        return AssistantMessage(content=[], api="x", provider="p", model="m", usage=Usage(), stop_reason="error", timestamp=0)

    down, bad = failed(), failed()
    retry.tag_if_transient(down, _Status(503), "m")
    retry.tag_if_transient(bad, _Status(400), "m")

    outcome = outcome_of(down)
    assert outcome is not None and outcome.kind == "interrupted"
    assert outcome_of(bad) is None
