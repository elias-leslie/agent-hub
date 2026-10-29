"""The model identity line: the model being called is named in the system prompt, harnesses excepted."""

from __future__ import annotations

from typing import Any

import pytest

from app.llm.api_registry import register_api_provider, unregister_api_providers
from app.llm.event_stream import AssistantMessageEventStream
from app.llm.model_resolver import resolve_llm_model
from app.llm.providers import claude_code_cli  # noqa: F401  (registers the harness provider)
from app.llm.stream import model_identity_line, stream_simple
from app.llm.types import Context, Model, ModelCost, UserMessage

_SOURCE = "model-identity-test"


class _Recorder:
    api = "recording-api"

    def __init__(self) -> None:
        self.contexts: list[Context] = []

    def stream(self, model: Model[Any], context: Context, options: Any = None) -> AssistantMessageEventStream:
        self.contexts.append(context)
        return AssistantMessageEventStream()

    stream_simple = stream


def _model(name: str, model_id: str) -> Model[Any]:
    return Model(
        id=model_id, name=name, api="recording-api", provider="test", base_url="", reasoning=False,
        input=["text"], cost=ModelCost(input=0.0, output=0.0, cache_read=0.0, cache_write=0.0),
        context_window=1000, max_tokens=100,
    )


@pytest.fixture
def recorder():
    rec = _Recorder()
    register_api_provider(rec, _SOURCE)
    yield rec
    unregister_api_providers(_SOURCE)


def _context(system: str | None) -> Context:
    return Context(messages=[UserMessage(content="hi", timestamp=0)], system_prompt=system)


def test_identity_names_the_model_actually_called_after_a_switch(recorder: _Recorder) -> None:
    first, second = _model("Alpha One", "alpha-1"), _model("Beta Two", "beta-2")
    context = _context("Stable prefix.")
    stream_simple(first, context)
    stream_simple(second, context)

    sent_first, sent_second = (c.system_prompt or "" for c in recorder.contexts)
    assert sent_first.startswith("Stable prefix.\n\n")
    assert "Alpha One (model id alpha-1)" in sent_first and "Beta" not in sent_first
    assert sent_second.startswith("Stable prefix.\n\n")
    assert "Beta Two (model id beta-2)" in sent_second and "Alpha" not in sent_second
    assert context.system_prompt == "Stable prefix."  # the caller's context is left alone


def test_identity_is_the_last_thing_so_the_prefix_stays_cacheable(recorder: _Recorder) -> None:
    model = _model("Alpha One", "alpha-1")
    stream_simple(model, _context("Stable prefix."))
    stream_simple(model, _context("Stable prefix."))
    assert recorder.contexts[0].system_prompt == recorder.contexts[1].system_prompt
    assert (recorder.contexts[0].system_prompt or "").endswith(model_identity_line(model))


def test_identity_without_a_system_prompt_and_without_a_second_id(recorder: _Recorder) -> None:
    stream_simple(_model("same", "same"), _context(None))
    sent = recorder.contexts[0].system_prompt or ""
    assert sent == model_identity_line(_model("same", "same"))
    assert "model id" not in sent


def test_identity_uses_catalog_display_name() -> None:
    model = resolve_llm_model("opencode-go/deepseek-v4.1-flash", "opencode-go")
    assert "DeepSeek V4.1 Flash" in model_identity_line(model)


def test_harness_provider_that_states_its_own_model_gets_no_line() -> None:
    from app.llm.api_registry import get_api_provider

    model = resolve_llm_model("claude-sonnet-5-5", "claude")
    assert model.api == "claude-code-cli"
    seen: list[Context] = []
    real = get_api_provider("claude-code-cli")
    assert real is not None
    original = real.stream_simple
    real.stream_simple = lambda m, c, o=None: (seen.append(c), AssistantMessageEventStream())[1]  # type: ignore[method-assign]
    try:
        stream_simple(model, _context("Stable prefix."))
    finally:
        real.stream_simple = original  # type: ignore[method-assign]
    assert seen[0].system_prompt == "Stable prefix."
