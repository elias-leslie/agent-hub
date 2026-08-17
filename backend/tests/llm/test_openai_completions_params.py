from __future__ import annotations

from app.llm.model_resolver import resolve_llm_model
from app.llm.providers.openai_completions import _get_compat, _prepare_sdk_body, build_params
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
