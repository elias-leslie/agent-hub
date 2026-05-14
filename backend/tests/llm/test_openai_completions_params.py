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
