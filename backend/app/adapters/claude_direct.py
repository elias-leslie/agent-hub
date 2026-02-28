"""Direct Anthropic API helpers for Claude adapter (OAuth token path)."""

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from app.adapters.base import (
    CompletionResult,
    Message,
    ProviderError,
    StreamEvent,
)

logger = logging.getLogger(__name__)

# Anthropic API valid fields per content block type.
# Extra fields (tool_name, thought_signature) added by the shared streaming
# layer for other providers must be stripped before sending to Anthropic.
VALID_BLOCK_FIELDS: dict[str, set[str]] = {
    "text": {"type", "text"},
    "tool_use": {"type", "id", "name", "input"},
    "tool_result": {"type", "tool_use_id", "content", "is_error"},
    "image": {"type", "source"},
}


def sanitize_content(
    content: str | list[dict[str, Any]],
) -> str | list[dict[str, Any]]:
    """Strip non-Anthropic fields from content blocks.

    The shared streaming tool loop adds extra fields (``tool_name`` on
    tool_result, ``thought_signature`` on tool_use) for other providers.
    The Anthropic API rejects unknown fields, so they must be removed.
    """
    if isinstance(content, str):
        return content
    sanitized: list[dict[str, Any]] = []
    for block in content:
        block_type = block.get("type", "")
        allowed = VALID_BLOCK_FIELDS.get(block_type)
        if allowed:
            sanitized.append({k: v for k, v in block.items() if k in allowed})
        else:
            sanitized.append(block)
    return sanitized


def convert_messages(
    messages: list[Message],
) -> tuple[str, list[dict[str, Any]]]:
    """Convert internal Message format to Anthropic API format.

    Returns (system_text, api_messages).
    """
    system_parts: list[str] = []
    api_messages: list[dict[str, Any]] = []

    for msg in messages:
        if msg.role == "system":
            system_parts.append(msg.content if isinstance(msg.content, str) else "")
        else:
            api_messages.append({
                "role": msg.role,
                "content": sanitize_content(msg.content),
            })

    return "\n\n".join(system_parts), api_messages


def apply_cache_control(
    system_text: str, cache_retention: str
) -> str | list[dict[str, Any]]:
    """Wrap system text with cache_control if retention is requested.

    Returns a plain string (no caching) or a list-of-blocks with
    ``cache_control`` set (for prompt caching).
    """
    if cache_retention == "none" or not system_text:
        return system_text
    ttl = "1h" if cache_retention == "long" else "5m"
    return [
        {
            "type": "text",
            "text": system_text,
            "cache_control": {"type": "ephemeral", "ttl": ttl},
        }
    ]


async def ensure_valid_token() -> str:
    """Get a valid OAuth access token, refreshing if needed.

    Returns the access token string.
    """
    from app.services.credential_manager import get_credential_manager

    cm = get_credential_manager()
    token_json = cm.get("claude", "oauth_token")
    if not token_json:
        raise ProviderError(
            "No Claude OAuth token available", provider="claude", retriable=False
        )

    try:
        data = json.loads(token_json)
    except (json.JSONDecodeError, TypeError):
        return token_json

    access_token = data.get("access_token")
    expires_at = data.get("expires_at")

    if expires_at and time.time() >= (expires_at - 60):
        return await _refresh_token(cm, data)

    if not access_token:
        raise ProviderError(
            "Claude OAuth token data missing access_token",
            provider="claude",
            retriable=False,
        )
    return access_token


async def _refresh_token(cm: Any, data: dict[str, Any]) -> str:
    """Refresh an expired OAuth token and update credential manager."""
    from app.adapters.claude_auth import refresh_claude_token

    refresh_token = cm.get("claude", "refresh_token")
    if not refresh_token:
        raise ProviderError(
            "Claude OAuth token expired and no refresh token available",
            provider="claude",
            retriable=False,
        )

    logger.info("Refreshing expired Claude OAuth token")
    new_creds = await refresh_claude_token(refresh_token)

    new_data = json.dumps({
        "access_token": new_creds.access_token,
        "expires_at": new_creds.expires_at,
    })
    cm.set("claude", "oauth_token", new_data)
    if new_creds.refresh_token:
        cm.set("claude", "refresh_token", new_creds.refresh_token)

    return new_creds.access_token


def _build_create_kwargs(
    api_model: str,
    api_messages: list[dict[str, Any]],
    system_text: str,
    max_tokens: int,
    temperature: float,
    cache_retention: str,
) -> dict[str, Any]:
    """Build the kwargs dict for the Anthropic messages.create / stream call."""
    create_kwargs: dict[str, Any] = {
        "model": api_model,
        "messages": api_messages,
        "max_tokens": max_tokens,
    }
    if system_text:
        create_kwargs["system"] = apply_cache_control(system_text, cache_retention)
    if temperature != 1.0:
        create_kwargs["temperature"] = temperature
    return create_kwargs


def _parse_completion_response(
    response: Any,
    api_model: str,
    provider_name: str,
    start_time: float,
) -> CompletionResult:
    """Parse an Anthropic messages.create response into a CompletionResult."""
    content = "".join(block.text for block in response.content if block.type == "text")
    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    duration_ms = int((time.time() - start_time) * 1000)
    logger.info(
        "Claude direct API: %dms, model=%s, tokens=%d/%d",
        duration_ms, api_model, input_tokens, output_tokens,
    )
    return CompletionResult(
        content=content,
        model=api_model,
        provider=provider_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        finish_reason=response.stop_reason or "end_turn",
        raw_response=None,
    )


async def complete_direct(
    messages: list[Message],
    model: str,
    api_model_map: dict[str, str],
    provider_name: str,
    max_tokens: int | None = None,
    temperature: float = 1.0,
    cache_retention: str = "none",
    **kwargs: Any,
) -> CompletionResult:
    """Complete using direct Anthropic API with OAuth token."""
    import anthropic

    start_time = time.time()
    token = await ensure_valid_token()
    api_model = api_model_map.get(model, model)

    system_text, api_messages = convert_messages(messages)
    create_kwargs = _build_create_kwargs(
        api_model, api_messages, system_text,
        max_tokens or 4096, temperature, cache_retention,
    )

    client = anthropic.AsyncAnthropic(auth_token=token)
    try:
        response = await client.messages.create(**create_kwargs)
        return _parse_completion_response(response, api_model, provider_name, start_time)
    finally:
        await client.close()


async def _stream_events(
    client: Any,
    create_kwargs: dict[str, Any],
    abort_event: "asyncio.Event | None",
) -> AsyncIterator[StreamEvent]:
    """Yield StreamEvents from the Anthropic streaming API."""
    final_message = None
    async with client.messages.stream(**create_kwargs) as stream:
        async for event in stream:
            if abort_event is not None and abort_event.is_set():
                raise asyncio.CancelledError("Abort signal received")
            if event.type == "content_block_delta" and hasattr(event, "delta"):
                if hasattr(event.delta, "text"):
                    yield StreamEvent(type="content", content=event.delta.text)
                elif hasattr(event.delta, "thinking"):
                    yield StreamEvent(type="thinking", content=event.delta.thinking)
        final_message = await stream.get_final_message()

    if final_message is None:
        return

    finish_reason = final_message.stop_reason or "end_turn"
    for block in final_message.content:
        if hasattr(block, "type") and block.type == "tool_use":
            yield StreamEvent(
                type="tool_use",
                tool_id=block.id,
                tool_name=block.name,
                tool_input=block.input if isinstance(block.input, dict) else {},
            )

    yield StreamEvent(
        type="done",
        input_tokens=final_message.usage.input_tokens,
        output_tokens=final_message.usage.output_tokens,
        finish_reason=finish_reason,
    )


async def stream_direct(
    messages: list[Message],
    model: str,
    api_model_map: dict[str, str],
    max_tokens: int | None = None,
    temperature: float = 1.0,
    cache_retention: str = "none",
    **kwargs: Any,
) -> AsyncIterator[StreamEvent]:
    """Stream using direct Anthropic API with OAuth token."""
    import anthropic

    token = await ensure_valid_token()
    api_model = api_model_map.get(model, model)

    system_text, api_messages = convert_messages(messages)
    create_kwargs = _build_create_kwargs(
        api_model, api_messages, system_text,
        max_tokens or 4096, temperature, cache_retention,
    )

    tools = kwargs.get("tools")
    if tools:
        create_kwargs["tools"] = tools

    thinking_level = kwargs.get("thinking_level")
    if thinking_level:
        from app.adapters.claude_utils import get_claude_thinking_config

        thinking_config = get_claude_thinking_config(thinking_level)
        if thinking_config:
            create_kwargs["thinking"] = thinking_config
            create_kwargs["max_tokens"] = max(create_kwargs["max_tokens"], 1024)

    abort_event: asyncio.Event | None = kwargs.get("abort_event")

    client = anthropic.AsyncAnthropic(auth_token=token)
    try:
        async for event in _stream_events(client, create_kwargs, abort_event):
            yield event
    except Exception as e:
        logger.error("Claude direct API stream error: %s", e)
        yield StreamEvent(type="error", error=str(e))
    finally:
        await client.close()
