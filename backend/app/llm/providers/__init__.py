"""LLM provider implementations.

Each module in this package registers exactly one :class:`ApiProvider`
via :func:`backend.app.llm.api_registry.register_api_provider` at import.
Per D8, no module outside ``backend/app/llm/`` is allowed to import
providers directly; all access goes through ``api_registry.get_api_provider``.
"""

from __future__ import annotations

from ..api_registry import register_api_provider

# Import built-in providers for their register_api_provider side effects.
from . import anthropic as anthropic
from . import google as google
from . import openai_codex_responses as openai_codex_responses
from . import openai_completions as openai_completions


def register_builtin_providers() -> None:
    """Register the built-in providers idempotently."""
    for provider in (
        anthropic.anthropic_provider,
        google.google_provider,
        openai_codex_responses.openai_codex_responses_provider,
        openai_completions.openai_completions_provider,
    ):
        register_api_provider(provider)


register_builtin_providers()
