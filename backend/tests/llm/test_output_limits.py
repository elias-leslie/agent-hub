"""Output limits come from the model catalog; an uncatalogued model is logged, not silently assumed."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from app.api.complete.turn_budget import tool_loop_turns
from app.constants.agent_limits import DEFAULT_AGENTIC_MAX_TURNS
from app.constants.catalog import INACTIVE_MODEL_CATALOG_BY_ID, MODEL_CATALOG_BY_ID
from app.llm import tool_loop
from app.llm.model_resolver import resolve_llm_model
from app.llm.providers.anthropic import AnthropicOptions, build_params
from app.llm.types import Context, Model, ModelCost, UserMessage


def _anthropic_model(max_tokens: int) -> Model[Any]:
    return Model[Any](
        id="claude-sonnet-5-5", name="Sonnet", api="anthropic-messages", provider="anthropic",
        base_url="https://api.anthropic.com", reasoning=True, input=["text"],
        cost=ModelCost(input=3.0, output=15.0, cache_read=0.3, cache_write=3.75),
        context_window=200_000, max_tokens=max_tokens,
    )


def _context() -> Context:
    return Context(messages=[UserMessage(content="hi", timestamp=0)])


def test_anthropic_max_tokens_defaults_to_the_catalog_limit() -> None:
    params = build_params(_anthropic_model(64_000), _context(), None)

    assert params["max_tokens"] == 64_000


def test_an_explicit_max_tokens_wins() -> None:
    params = build_params(_anthropic_model(64_000), _context(), AnthropicOptions(max_tokens=1_000))

    assert params["max_tokens"] == 1_000


def test_the_thinking_budget_stays_below_max_tokens() -> None:
    roomy = build_params(_anthropic_model(64_000), _context(), AnthropicOptions(thinking_enabled=True, thinking_budget_tokens=16_384))
    tight = build_params(_anthropic_model(64_000), _context(), AnthropicOptions(thinking_enabled=True, thinking_budget_tokens=16_384, max_tokens=2_000))

    assert (roomy["max_tokens"], roomy["thinking"]["budget_tokens"]) == (64_000, 16_384)
    assert tight["thinking"]["budget_tokens"] < tight["max_tokens"] == 2_000


def test_a_catalogued_model_uses_its_catalog_limits(caplog: pytest.LogCaptureFixture) -> None:
    entry = MODEL_CATALOG_BY_ID["codex/gpt-6.1-sol"]
    with caplog.at_level(logging.WARNING, logger="app.llm.model_resolver"):
        model = resolve_llm_model("codex/gpt-6.1-sol", "codex")

    assert (model.max_tokens, model.context_window) == (entry.capabilities.max_output_tokens, entry.context_window)
    assert not caplog.records


def test_an_inactive_catalog_row_still_supplies_its_limits(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    entry = MODEL_CATALOG_BY_ID["codex/gpt-6.1-sol"]
    retired = type(entry)(**{**entry.__dict__, "id": "codex/retired-model", "alias": "", "upstream_id": "retired-upstream"})
    monkeypatch.setitem(INACTIVE_MODEL_CATALOG_BY_ID, retired.id, retired)
    with caplog.at_level(logging.WARNING, logger="app.llm.model_resolver"):
        by_id = resolve_llm_model("codex/retired-model", "codex")
        by_upstream = resolve_llm_model("retired-upstream", "codex")

    assert by_id.context_window == by_upstream.context_window == entry.context_window
    assert by_id.id == by_upstream.id == "retired-upstream"
    assert not caplog.records


def test_an_uncatalogued_model_warns_naming_the_model(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="app.llm.model_resolver"):
        model = resolve_llm_model("codex/not-a-real-model", "codex")

    assert (model.max_tokens, model.context_window) == (8192, 128_000)
    assert any("codex/not-a-real-model" in r.getMessage() for r in caplog.records)


def test_no_caller_is_capped_at_one_or_thirty_two_turns() -> None:
    import inspect

    assert inspect.signature(tool_loop.run).parameters["max_turns"].default == DEFAULT_AGENTIC_MAX_TURNS
    assert tool_loop_turns(True, 1) == DEFAULT_AGENTIC_MAX_TURNS
    assert tool_loop_turns(True, 7) == 7
    assert tool_loop_turns(False, 1) == 1
