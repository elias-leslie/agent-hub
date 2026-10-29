"""Top-level stream/complete wrappers.

Direct port of pi-mono ``packages/ai/src/stream.ts``. The non-streaming
``complete()`` is simply ``stream().result()`` — every provider is native
streaming (per the convergence map).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .api_registry import ApiProvider, api_states_own_model, get_api_provider
from .env_api_keys import get_env_api_key
from .event_stream import AssistantMessageEventStream
from .types import (
    Api,
    AssistantMessage,
    Context,
    Model,
    ProviderStreamOptions,
    SimpleStreamOptions,
)


def _resolve_api_provider(api: Api) -> ApiProvider:
    provider = get_api_provider(api)
    if provider is None:
        raise RuntimeError(f"No API provider registered for api: {api}")
    return provider


def model_identity_line(model: Model[Any]) -> str:
    """One line telling the model which model it is: the catalog's display name and the id actually sent."""
    served = model.name if model.name == model.id else f"{model.name} (model id {model.id})"
    return f"You are running as {served} via Agent Hub. If asked which model you are, answer with this."


def with_model_identity(model: Model[Any], context: Context) -> Context:
    """The context for one provider call, with the identity line last in the system prompt.

    Built per call from the model being called, so a fallback or a mid-session model switch names the new model on
    the next call. Last keeps the stable prompt prefix cacheable; the line only changes with the model, which already
    keys the provider's cache. Harness providers state their own model, so they get the context unchanged.
    """
    if api_states_own_model(model.api):
        return context
    prompt = "\n\n".join(part for part in (context.system_prompt, model_identity_line(model)) if part)
    return replace(context, system_prompt=prompt)


def stream(
    model: Model[Any],
    context: Context,
    options: ProviderStreamOptions | None = None,
) -> AssistantMessageEventStream:
    provider = _resolve_api_provider(model.api)
    return provider.stream(model, with_model_identity(model, context), options)


async def complete(
    model: Model[Any],
    context: Context,
    options: ProviderStreamOptions | None = None,
) -> AssistantMessage:
    s = stream(model, context, options)
    return await s.result()


def stream_simple(
    model: Model[Any],
    context: Context,
    options: SimpleStreamOptions | None = None,
) -> AssistantMessageEventStream:
    provider = _resolve_api_provider(model.api)
    return provider.stream_simple(model, with_model_identity(model, context), options)


async def complete_simple(
    model: Model[Any],
    context: Context,
    options: SimpleStreamOptions | None = None,
) -> AssistantMessage:
    s = stream_simple(model, context, options)
    return await s.result()


__all__ = [
    "complete",
    "complete_simple",
    "get_env_api_key",
    "model_identity_line",
    "stream",
    "stream_simple",
    "with_model_identity",
]
