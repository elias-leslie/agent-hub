"""Top-level stream/complete wrappers.

Direct port of pi-mono ``packages/ai/src/stream.ts``. The non-streaming
``complete()`` is simply ``stream().result()`` — every provider is native
streaming (per the convergence map).
"""

from __future__ import annotations

from typing import Any

from .api_registry import ApiProvider, get_api_provider
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


def stream(
    model: Model[Any],
    context: Context,
    options: ProviderStreamOptions | None = None,
) -> AssistantMessageEventStream:
    provider = _resolve_api_provider(model.api)
    return provider.stream(model, context, options)


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
    return provider.stream_simple(model, context, options)


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
    "stream",
    "stream_simple",
]
