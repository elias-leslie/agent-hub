from __future__ import annotations

from app.llm.providers.openai_completions import _prepare_sdk_body


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
