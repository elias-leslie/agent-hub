"""Tests for provider-specific thinking configuration."""

from app.adapters.thinking import get_thinking_config


def test_xai_does_not_send_reasoning_effort() -> None:
    """xAI models reject OpenAI-style reasoning_effort parameters."""
    assert get_thinking_config("xai/grok-code-fast-1", "high", "xai") is None
    assert get_thinking_config("xai/grok-4.20-reasoning", "high", "xai") is None


def test_xai_multi_agent_does_not_send_reasoning_effort() -> None:
    """Live xAI endpoint currently rejects reasoning effort for multi-agent."""
    assert get_thinking_config("xai/grok-4.20-multi-agent", "xhigh", "xai") is None


def test_openrouter_still_uses_reasoning_effort() -> None:
    """OpenRouter keeps the OpenAI-style reasoning mapping."""
    assert get_thinking_config("openrouter/any-model", "high", "openrouter") == {
        "reasoning_effort": "high"
    }


def test_none_disables_reasoning_for_openai_style_providers() -> None:
    """Literal 'none' should disable reasoning params instead of sending an invalid value."""
    assert get_thinking_config("codex/gpt-5.4", "none", "codex") is None
    assert get_thinking_config("openai/gpt-5.2", "none", "openai") is None
