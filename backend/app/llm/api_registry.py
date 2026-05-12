"""ApiProvider protocol + registry.

Direct port of pi-mono ``packages/ai/src/api-registry.ts``. Per D8, every
file in ``backend/app/llm/providers/`` declares exactly one
:func:`register_api_provider` call at module import.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from .event_stream import AssistantMessageEventStream
from .types import (
    Api,
    Context,
    Model,
    SimpleStreamOptions,
    StreamOptions,
)


@runtime_checkable
class ApiProvider(Protocol):
    """The pi-mono universal interface.

    Exactly two methods. Providers register themselves keyed by ``api``
    (e.g. ``"anthropic-messages"``, ``"openai-completions"``); the registry
    is queried by ``Model.api`` at stream time.

    Per the convergence map, NOTHING else lives on this protocol —
    ``health_check`` is a separate module (D3) and ``complete()`` /
    ``complete_with_tools()`` are dead (D6).
    """

    api: Api

    def stream(
        self,
        model: Model[Any],
        context: Context,
        options: StreamOptions | None = None,
    ) -> AssistantMessageEventStream:
        """Async-iterable + terminal-result stream. Errors are encoded in the
        stream, never raised."""
        ...

    def stream_simple(
        self,
        model: Model[Any],
        context: Context,
        options: SimpleStreamOptions | None = None,
    ) -> AssistantMessageEventStream:
        """As :meth:`stream`, but accepting ``SimpleStreamOptions`` (with the
        unified ``reasoning`` parameter)."""
        ...


@dataclass(slots=True)
class _RegisteredApiProvider:
    provider: ApiProvider
    source_id: str | None = None


_registry: dict[str, _RegisteredApiProvider] = {}


def _wrap_for_api(api: Api, provider: ApiProvider) -> ApiProvider:
    """Returns a thin wrapper that asserts ``model.api == api`` at call time.

    Pi-mono's ``wrapStream``/``wrapStreamSimple`` guard against catalog
    misconfiguration. Same guard here.
    """

    class _ApiGuard:
        api = provider.api

        def stream(
            self,
            model: Model[Any],
            context: Context,
            options: StreamOptions | None = None,
        ) -> AssistantMessageEventStream:
            if model.api != api:
                raise ValueError(f"Mismatched api: {model.api} expected {api}")
            return provider.stream(model, context, options)

        def stream_simple(
            self,
            model: Model[Any],
            context: Context,
            options: SimpleStreamOptions | None = None,
        ) -> AssistantMessageEventStream:
            if model.api != api:
                raise ValueError(f"Mismatched api: {model.api} expected {api}")
            return provider.stream_simple(model, context, options)

    return _ApiGuard()


def register_api_provider(provider: ApiProvider, source_id: str | None = None) -> None:
    _registry[provider.api] = _RegisteredApiProvider(
        provider=_wrap_for_api(provider.api, provider),
        source_id=source_id,
    )


def get_api_provider(api: Api) -> ApiProvider | None:
    entry = _registry.get(api)
    return entry.provider if entry else None


def get_api_providers() -> list[ApiProvider]:
    return [entry.provider for entry in _registry.values()]


def unregister_api_providers(source_id: str) -> None:
    for api in list(_registry.keys()):
        if _registry[api].source_id == source_id:
            del _registry[api]


def clear_api_providers() -> None:
    _registry.clear()


__all__ = [
    "ApiProvider",
    "clear_api_providers",
    "get_api_provider",
    "get_api_providers",
    "register_api_provider",
    "unregister_api_providers",
]
