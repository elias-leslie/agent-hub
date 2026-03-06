"""Tests for provider-specific thinking configuration."""

from app.adapters.thinking import get_thinking_config


def test_xai_does_not_send_reasoning_effort() -> None:
    """xAI models reject OpenAI-style reasoning_effort parameters."""
    assert get_thinking_config("xai/grok-code-fast-1", "high", "xai") is None


def test_openrouter_still_uses_reasoning_effort() -> None:
    """OpenRouter keeps the OpenAI-style reasoning mapping."""
    assert get_thinking_config("openrouter/any-model", "high", "openrouter") == {
        "reasoning_effort": "high"
    }
