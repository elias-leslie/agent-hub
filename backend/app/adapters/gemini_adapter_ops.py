"""Health check and tool operations for the Gemini adapter."""

import logging
from collections.abc import AsyncIterator
from typing import Any

from app.adapters._errors_types import ProviderError
from app.adapters.base import CompletionResult, Message
from app.adapters.gemini_tools import execute_tool_loop
from app.adapters.gemini_utils import do_complete_call

logger = logging.getLogger(__name__)


async def sdk_health_check(client: Any) -> bool:
    """Check reachability using the GenAI SDK client (zero tokens consumed)."""
    from app.constants import GEMINI_FLASH

    model_info = await client.aio.models.get(model=GEMINI_FLASH)
    return model_info is not None


async def sdk_complete(
    client: Any,
    messages: list[Message],
    model: str,
    temperature: float,
    max_tokens: int | None,
    provider_name: str,
    kwargs: dict[str, Any],
) -> CompletionResult:
    """Complete using the GenAI SDK with retry."""
    from app.adapters.errors import with_retry

    @with_retry
    async def _do() -> CompletionResult:
        return await do_complete_call(
            client, messages, model, temperature, max_tokens, provider_name, kwargs,
        )

    return await _do()


async def sdk_complete_with_failover(
    sdk_clients: list[Any],
    client: Any,
    messages: list[Message],
    model: str,
    temperature: float,
    max_tokens: int | None,
    provider_name: str,
    kwargs: dict[str, Any],
) -> CompletionResult:
    """Try each SDK client in order; raise last error if all fail."""
    if not sdk_clients:
        if client is None:
            raise ProviderError(
                "Gemini API key is not configured",
                provider=provider_name,
                retriable=False,
            )
        return await sdk_complete(client, messages, model, temperature, max_tokens, provider_name, kwargs)

    last_error: ProviderError | None = None
    for i, c in enumerate(sdk_clients):
        try:
            result = await sdk_complete(c, messages, model, temperature, max_tokens, provider_name, kwargs)
            if i > 0:
                logger.info("Gemini: API key #%d succeeded after %d failure(s)", i + 1, i)
            return result
        except ProviderError as e:
            last_error = e
            if not e.retriable:
                raise
            logger.warning("Gemini API key #%d rate-limited for %s, trying next key", i + 1, model)

    if last_error:
        raise last_error
    return await sdk_complete(client, messages, model, temperature, max_tokens, provider_name, kwargs)


async def tool_loop(
    sdk_client: Any,
    messages: list[Message],
    model: str,
    tools: list[dict[str, Any]],
    working_dir: str | None,
    max_tokens: int | None,
    max_turns: int,
    provider_name: str,
    project_id: str | None,
    **kwargs: Any,
) -> AsyncIterator[tuple[Any, str | None]]:
    """Run the SDK-backed Gemini tool loop."""
    sdk_clients = sdk_client if isinstance(sdk_client, list) else ([sdk_client] if sdk_client is not None else [])
    if not sdk_clients:
        raise ProviderError("Gemini API key is not configured", provider=provider_name, retriable=False)
    last_error: ProviderError | None = None
    for i, client in enumerate(sdk_clients):
        try:
            buffered: list[tuple[Any, str | None]] = []
            async for event in execute_tool_loop(
                client=client,
                messages=messages,
                model=model,
                tools=tools,
                working_dir=working_dir,
                max_tokens=max_tokens,
                max_turns=max_turns,
                provider_name=provider_name,
                project_id=project_id,
                **kwargs,
            ):
                buffered.append(event)
            if i > 0:
                logger.info("Gemini: API key #%d tool loop succeeded after %d failure(s)", i + 1, i)
            for event in buffered:
                yield event
            return
        except ProviderError as e:
            last_error = e
            if not e.retriable:
                raise
            logger.warning("Gemini API key #%d tool loop failed for %s, trying next key", i + 1, model)
    if last_error:
        raise last_error
