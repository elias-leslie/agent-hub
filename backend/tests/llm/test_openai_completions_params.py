from __future__ import annotations

import pytest

from app.config import settings
from app.llm.model_resolver import resolve_llm_model
from app.llm.providers.openai_completions import (
    OpenAICompletionsOptions,
    _get_compat,
    _prepare_sdk_body,
    build_params,
)
from app.llm.types import Context, UserMessage


def test_provider_specific_fields_move_to_extra_body() -> None:
    body = _prepare_sdk_body(
        {
            "model": "deepseek-ai/deepseek-v4-flash",
            "messages": [{"role": "user", "content": "hi"}],
            "reasoning_effort": "low",
            "thinking": {"type": "enabled"},
            "provider": {"only": ["moonshotai"]},
        }
    )

    assert body["model"] == "deepseek-ai/deepseek-v4-flash"
    assert body["reasoning_effort"] == "low"
    assert body["extra_body"] == {
        "thinking": {"type": "enabled"},
        "provider": {"only": ["moonshotai"]},
    }


def test_moonshot_uses_system_role_and_plain_max_tokens() -> None:
    model = resolve_llm_model("moonshot/kimi-k2.6", "moonshot")
    compat = _get_compat(model)

    params = build_params(
        model,
        Context(
            messages=[UserMessage(content="hi", timestamp=1)],
            system_prompt="system prompt",
        ),
        None,
        compat,
        "none",
    )

    assert params["messages"][0] == {"role": "system", "content": "system prompt"}
    assert "store" not in params
    assert "max_completion_tokens" not in params
    assert compat.max_tokens_field == "max_tokens"


def test_local_gemma_adds_ollama_keep_alive_to_extra_body() -> None:
    model = resolve_llm_model("local/gemma4:12b-it-qat", "local")
    compat = _get_compat(model)

    params = build_params(
        model,
        Context(messages=[UserMessage(content="critique this", timestamp=1)]),
        None,
        compat,
        "none",
    )
    body = _prepare_sdk_body(params)

    assert params["keep_alive"] == "5m"
    assert body["extra_body"]["keep_alive"] == "5m"


def test_local_non_reasoning_model_explicitly_disables_ollama_thinking() -> None:
    """Ollama reasons by default; silence has to be requested.

    ``local/gemma4:12b-it-qat`` is catalogued with ``has_thinking=False``, so every
    ``model.reasoning``-gated branch is skipped and no reasoning field used to be
    sent at all. Ollama then reasoned anyway, spent the whole ``max_tokens`` budget
    on hidden reasoning and returned HTTP 200 with ``content=""`` — silently killing
    the local rung that 77 of 79 active agents fall back to.
    """
    model = resolve_llm_model("local/gemma4:12b-it-qat", "local")
    compat = _get_compat(model)

    assert compat.reasons_by_default is True
    assert model.reasoning is False

    params = build_params(
        model,
        Context(messages=[UserMessage(content="Reply with exactly: OK", timestamp=1)]),
        None,
        compat,
        "none",
    )

    assert params["reasoning_effort"] == "none"


def test_remote_non_reasoning_model_does_not_get_reasoning_effort() -> None:
    """The Ollama workaround must not leak onto hosted providers."""
    model = resolve_llm_model("nvidia/gpt-oss-120b", "nvidia")
    compat = _get_compat(model)

    assert compat.reasons_by_default is False

    params = build_params(
        model,
        Context(messages=[UserMessage(content="hi", timestamp=1)]),
        None,
        compat,
        "none",
    )

    assert "reasoning_effort" not in params


@pytest.mark.parametrize(
    ("effort", "upstream_effort"),
    [
        (None, "none"),
        ("minimal", "none"),
        ("low", "low"),
        ("medium", "medium"),
        ("high", None),
        ("xhigh", None),
    ],
)
def test_local_qwen_ollama_uses_supported_reasoning_effort(
    monkeypatch: pytest.MonkeyPatch,
    effort,
    upstream_effort,
) -> None:
    monkeypatch.setattr(settings, "local_openai_base_url", "http://127.0.0.1:11434/v1")
    model = resolve_llm_model("local/qwen3.8-27b-gsq-rco-iq3_s", "local")
    params = build_params(
        model,
        Context(messages=[UserMessage(content="Reply with exactly: OK", timestamp=1)]),
        OpenAICompletionsOptions(reasoning_effort=effort, max_tokens=128),
        _get_compat(model),
        "none",
    )
    body = _prepare_sdk_body(params)

    # Ollama ignores llama.cpp template kwargs and budget fields. Its API rejects
    # xhigh, while this Qwen template rejects high/max; upper levels use its default.
    assert body.get("reasoning_effort") == upstream_effort
    if upstream_effort is None:
        assert "reasoning_effort" not in body
    assert "chat_template_kwargs" not in params
    assert "reasoning_budget_tokens" not in params
    assert body["max_tokens"] == 128


@pytest.mark.parametrize(
    ("effort", "budget"),
    [(None, None), ("low", 512), ("medium", 1024), ("xhigh", 2048)],
)
def test_local_qwen_llama_cpp_keeps_chat_template_controls(
    monkeypatch: pytest.MonkeyPatch,
    effort,
    budget,
) -> None:
    monkeypatch.setattr(settings, "local_openai_base_url", "http://127.0.0.1:8080/v1")
    model = resolve_llm_model("local/qwen3.8-27b-gsq-rco-iq3_s", "local")
    params = build_params(
        model,
        Context(messages=[UserMessage(content="hi", timestamp=1)]),
        OpenAICompletionsOptions(reasoning_effort=effort),
        _get_compat(model),
        "none",
    )
    body = _prepare_sdk_body(params)

    assert "reasoning_effort" not in body
    assert body["extra_body"]["chat_template_kwargs"] == {
        "enable_thinking": bool(effort),
        "preserve_thinking": True,
    }
    assert body["extra_body"].get("reasoning_budget_tokens") == budget


def test_base_url_provider_detection_matches_host_not_substring() -> None:
    from app.llm.providers.openai_completions import _host_is

    assert _host_is("https://api.deepseek.com/v1", "deepseek.com")
    assert _host_is("https://API.OpenAI.com/v1", "api.openai.com")
    assert _host_is("api.minimax.io/v1", "api.minimax.io")
    assert not _host_is("https://proxy.example.net/deepseek.com/v1", "deepseek.com")
    assert not _host_is("https://api.openai.com.example.net/v1", "api.openai.com")
    assert not _host_is("https://notdeepseek.com/v1", "deepseek.com")
    assert not _host_is("", "deepseek.com")
