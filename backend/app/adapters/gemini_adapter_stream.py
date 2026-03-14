"""SDK streaming path for the Gemini adapter."""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from app.adapters._errors_types import ProviderError
from app.adapters.base import StreamEvent
from app.adapters.gemini_thinking import get_thinking_level
from app.adapters.gemini_utils import (
    build_stream_config,
    convert_messages,
    extract_chunk_tool_events,
)

logger = logging.getLogger(__name__)

_GENERATE_MAX_RETRIES = 4
_GENERATE_RETRY_BASE_DELAY = 2.0
_GENERATE_RETRY_MAX_DELAY = 90.0
_RETRYABLE_STATUSES: frozenset[int] = frozenset({429, 500, 502, 503, 504})
_RETRYABLE_KEYWORDS = (
    "resource exhausted",
    "rate limit",
    "overloaded",
    "service unavailable",
    "deadline_exceeded",
    "http 429",
    "http 500",
    "http 502",
    "http 503",
    "http 504",
)


def _is_retryable_error(text: str) -> bool:
    """Check if an error string indicates a retryable condition."""
    lower = text.lower()
    return any(kw in lower for kw in _RETRYABLE_KEYWORDS)


def _compute_retry_delay(exc: Exception, attempt: int) -> float:
    """Compute delay before next retry, preferring any server hint."""
    from app.adapters.errors import extract_retry_delay

    server_delay = extract_retry_delay(exc)
    if server_delay is not None and server_delay > 0:
        return min(server_delay, _GENERATE_RETRY_MAX_DELAY)
    return min(_GENERATE_RETRY_BASE_DELAY * (2**attempt), _GENERATE_RETRY_MAX_DELAY)


def _get_quota_info(exc: Exception | None) -> str:
    """Extract quota details string for diagnostic logging."""
    if exc is None:
        return ""
    try:
        from app.adapters.gemini_errors import extract_gemini_quota_details

        quota = extract_gemini_quota_details(exc)
        if quota.get("quota_metric"):
            return (
                f" [metric={quota.get('quota_metric')}"
                f" limit={quota.get('quota_limit', '?')}"
                f" consumer={quota.get('consumer', '?')}]"
            )
    except Exception:
        logger.debug("Failed to extract quota details from error", exc_info=True)
    return ""


def _collect_usage(last_chunk: Any, total_content: str) -> tuple[int, int]:
    """Extract token counts from the final streaming chunk."""
    if last_chunk and last_chunk.usage_metadata:
        input_tokens = last_chunk.usage_metadata.prompt_token_count or 0
        output_tokens = last_chunk.usage_metadata.candidates_token_count or 0
        return input_tokens, output_tokens
    return 0, len(total_content) // 4


async def _iter_chunks(
    client: Any,
    model: str,
    contents: Any,
    config: Any,
    abort_event: asyncio.Event | None,
) -> AsyncIterator[Any]:
    """Yield raw SDK chunks, checking abort_event between each."""
    async for chunk in await client.aio.models.generate_content_stream(
        model=model, contents=contents, config=config,
    ):
        if abort_event is not None and abort_event.is_set():
            raise asyncio.CancelledError("Abort signal received")
        yield chunk


async def sdk_stream(
    client: Any,
    messages: Any,
    model: str,
    temperature: float,
    max_tokens: int | None,
    provider_name: str,
    kwargs: dict[str, Any],
) -> AsyncIterator[StreamEvent]:
    """Stream completion using the GenAI SDK (api_key / ADC auth mode).

    Yields StreamEvent objects for content, tool_use, and done/error.
    Retries on transient errors (429/5xx) if no content has been yielded yet.
    """
    system_instruction, contents = convert_messages(messages)
    config = build_stream_config(
        temperature=temperature,
        max_tokens=max_tokens,
        model=model,
        system_instruction=system_instruction,
        tools_defs=kwargs.get("tools"),
        thinking_level=get_thinking_level(model, kwargs.get("thinking_level")),
    )
    abort_event: asyncio.Event | None = kwargs.get("abort_event")

    for attempt in range(_GENERATE_MAX_RETRIES):
        total_content = ""
        last_chunk = None
        content_yielded = False

        try:
            async for chunk in _iter_chunks(client, model, contents, config, abort_event):
                last_chunk = chunk
                if chunk.text:
                    total_content += chunk.text
                    content_yielded = True
                    yield StreamEvent(type="content", content=chunk.text)
                for event in extract_chunk_tool_events(chunk):
                    content_yielded = True
                    yield event

            input_tokens, output_tokens = _collect_usage(last_chunk, total_content)
            yield StreamEvent(
                type="done",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                finish_reason="STOP",
            )
            return

        except Exception as e:
            quota_info = _get_quota_info(e)
            if content_yielded or not _is_retryable_error(str(e)):
                logger.error("Gemini stream error: %s%s", e, quota_info)
                yield StreamEvent(type="error", error=str(e))
                return

            delay = _compute_retry_delay(e, attempt)
            logger.warning(
                "Gemini stream retry %d/%d after %s (delay=%.1fs)%s",
                attempt + 1,
                _GENERATE_MAX_RETRIES,
                type(e).__name__,
                delay,
                quota_info,
            )
            await asyncio.sleep(delay)

    yield StreamEvent(type="error", error="Gemini stream retries exhausted")


async def sdk_stream_with_failover(
    sdk_clients: list[Any],
    client: Any,
    messages: Any,
    model: str,
    temperature: float,
    max_tokens: int | None,
    provider_name: str,
    kwargs: dict[str, Any],
) -> AsyncIterator[StreamEvent]:
    """Try SDK stream across keys; fail over on retryable pre-content errors."""
    if sdk_clients:
        clients = sdk_clients
    elif client is not None:
        clients = [client]
    else:
        raise ProviderError(
            "Gemini API key is not configured",
            provider=provider_name,
            retriable=False,
        )

    for i, c in enumerate(clients):
        emitted_non_error = False
        async for event in sdk_stream(c, messages, model, temperature, max_tokens, provider_name, kwargs):
            if event.type != "error":
                emitted_non_error = True
                yield event
                continue

            can_fail_over = (
                not emitted_non_error
                and i < len(clients) - 1
                and bool(event.error)
                and _is_retryable_error(event.error or "")
            )
            if can_fail_over:
                logger.warning(
                    "Gemini API key #%d stream failed (%s), trying next key", i + 1, event.error,
                )
                break
            yield event
            return
        else:
            return

    yield StreamEvent(type="error", error="Gemini stream retries exhausted across API keys")
