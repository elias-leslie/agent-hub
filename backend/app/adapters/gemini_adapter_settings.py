"""Gemini adapter client factories."""

from typing import Any

from google import genai


def make_sdk_client(api_key: str | None = None) -> genai.Client:
    """Create a GenAI SDK client with optional API key."""
    kwargs: dict[str, Any] = {}
    if api_key:
        kwargs["api_key"] = api_key
    return genai.Client(**kwargs)
