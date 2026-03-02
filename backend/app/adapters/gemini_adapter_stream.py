"""SDK streaming path for the Gemini adapter (api_key / ADC mode)."""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from app.adapters._gemini_cloudcode_ops import (
    _GENERATE_MAX_RETRIES,
    _compute_retry_delay,
    _get_quota_info,
    _is_retryable_error,
)
from app.adapters.base import StreamEvent
from app.adapters.gemini_thinking import get_thinking_level
from app.adapters.gemini_utils import (
    build_stream_config,
    convert_messages,
    extract_chunk_tool_events,
)

logger = logging.getLogger(__name__)


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
