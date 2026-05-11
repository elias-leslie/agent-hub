"""Direct Anthropic API helpers for Claude adapter (OAuth token and API key paths)."""

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from typing import Any, NoReturn

from app.adapters.base import (
    CompletionResult,
    Message,
    ProviderError,
    RateLimitError,
    StreamEvent,
)
from app.adapters.errors import extract_retry_delay
from app.constants.catalog_entries import get_max_output_tokens

logger = logging.getLogger(__name__)

# Required beta headers for OAuth token authentication.
# Without these, the Anthropic API rejects OAuth tokens with 401.
OAUTH_BETA_HEADERS = "claude-code-20250219,oauth-2025-04-20"

# Anthropic API valid fields per content block type.
# Extra fields (tool_name, thought_signature) added by the shared streaming
# layer for other providers must be stripped before sending to Anthropic.
VALID_BLOCK_FIELDS: dict[str, set[str]] = {
    "text": {"type", "text"},
    "tool_use": {"type", "id", "name", "input"},
    "tool_result": {"type", "tool_use_id", "content", "is_error"},
    "image": {"type", "source"},
}

MODELS_WITH_DEPRECATED_TEMPERATURE = {"claude-opus-4-7"}
DIRECT_THINKING_BUDGETS: dict[str, int] = {
    "low": 1024,
    "medium": 2048,
    "high": 4096,
    "xhigh": 8192,
    "ultrathink": 8192,
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


async def resolve_direct_credentials() -> tuple[str, str]:
    """Resolve credentials for the direct Anthropic API.

    Returns (credential_value, credential_type) where credential_type is
    ``"oauth_token"`` or ``"api_key"``.

    Resolution order: user preference > oauth_token > api_key.
    """
    from app.services.credential_manager import get_credential_manager

    cm = get_credential_manager()
    has_oauth = cm.get("claude", "oauth_token") is not None
    has_api_key = cm.get_api_key("claude") is not None

    if not has_oauth and not has_api_key:
        raise ProviderError(
            "No Claude credentials available (need OAuth token or API key)",
            provider="claude",
            retriable=False,
        )

    # Determine preferred auth method
    preferred = "oauth"
    if has_oauth and has_api_key:
        try:
            from app.api.preferences import get_preference_value
            from app.db import async_session

            async with async_session() as db:
                preferred = await get_preference_value(db, "claude_auth_preference", "oauth")
        except Exception:
            logger.debug("Could not read claude_auth_preference, defaulting to oauth")

    if preferred == "api_key" and has_api_key:
        return cm.get_api_key("claude"), "api_key"  # type: ignore[return-value]
    if has_oauth:
        token = await _ensure_valid_oauth_token(cm)
        return token, "oauth_token"
    # Only API key available
    return cm.get_api_key("claude"), "api_key"  # type: ignore[return-value]


async def ensure_valid_token() -> str:
    """Get a valid OAuth access token, refreshing if needed.

    Returns the access token string.  Kept for backward compatibility.
    """
    from app.services.credential_manager import get_credential_manager

    cm = get_credential_manager()
    return await _ensure_valid_oauth_token(cm)


async def _ensure_valid_oauth_token(cm: Any) -> str:
    """Get a valid OAuth access token from the credential manager."""
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

    # Persist refreshed token to DB so it survives server restarts
    try:
        from app.db import async_session
        from app.services.credential_upsert import upsert_credential

        async with async_session() as db:
            await upsert_credential(db, "claude", "oauth_token", new_data)
            if new_creds.refresh_token:
                await upsert_credential(db, "claude", "refresh_token", new_creds.refresh_token)
    except Exception:
        logger.warning("Failed to persist refreshed Claude token to DB", exc_info=True)

    return new_creds.access_token


def _build_client(credential: str, credential_type: str) -> Any:
    """Build an AsyncAnthropic client with the appropriate auth method."""
    import anthropic

    if credential_type == "api_key":
        return anthropic.AsyncAnthropic(api_key=credential)
    # OAuth token — requires beta headers
    return anthropic.AsyncAnthropic(
        auth_token=credential,
        default_headers={"anthropic-beta": OAUTH_BETA_HEADERS},
    )


def _resolve_model(model: str, credential_type: str, api_model_map: dict[str, str]) -> str:
    """Resolve model ID appropriate for the credential type.

    OAuth tokens require short model names (e.g. ``claude-sonnet-4-6``).
    API keys accept both short and dated names (e.g. ``claude-sonnet-4-6-20250514``).
    """
    if credential_type == "api_key":
        return api_model_map.get(model, model)
    # OAuth: use the model name as-is if it's already a full name without date,
    # otherwise map short names to their full (undated) form.
    from app.constants.models import CLAUDE_HAIKU, CLAUDE_OPUS, CLAUDE_SONNET

    OAUTH_MODEL_MAP: dict[str, str] = {
        "opus": CLAUDE_OPUS,
        "sonnet": CLAUDE_SONNET,
        "haiku": CLAUDE_HAIKU,
    }
    return OAUTH_MODEL_MAP.get(model, model)


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
    if temperature != 1.0 and api_model not in MODELS_WITH_DEPRECATED_TEMPERATURE:
        create_kwargs["temperature"] = temperature
    return create_kwargs


def _apply_optional_create_kwargs(
    create_kwargs: dict[str, Any],
    kwargs: dict[str, Any],
) -> None:
    tools = kwargs.get("tools")
    if tools:
        create_kwargs["tools"] = tools

    thinking_level = kwargs.get("thinking_level")
    if thinking_level:
        thinking_config = _get_direct_thinking_config(
            str(thinking_level),
            max_tokens=int(create_kwargs["max_tokens"]),
        )
        if thinking_config:
            create_kwargs["thinking"] = thinking_config


def _get_direct_thinking_config(
    thinking_level: str,
    max_tokens: int,
) -> dict[str, object] | None:
    target_budget = DIRECT_THINKING_BUDGETS.get(thinking_level)
    if target_budget is None:
        return None
    available_budget = max(max_tokens - 1024, 1024)
    return {"type": "enabled", "budget_tokens": min(target_budget, available_budget)}


def _is_temperature_deprecated_error(error: Exception) -> bool:
    return "`temperature` is deprecated" in str(error)


async def _create_with_temperature_retry(
    client: Any,
    create_kwargs: dict[str, Any],
) -> Any:
    try:
        async with client.messages.stream(**create_kwargs) as stream:
            return await stream.get_final_message()
    except Exception as exc:
        if "temperature" not in create_kwargs or not _is_temperature_deprecated_error(exc):
            raise
        retry_kwargs = dict(create_kwargs)
        retry_kwargs.pop("temperature", None)
        logger.info("Claude direct API rejected temperature; retrying without it")
        async with client.messages.stream(**retry_kwargs) as stream:
            return await stream.get_final_message()


def _raise_direct_api_error(error: Exception, provider_name: str) -> NoReturn:
    status_code = getattr(error, "status_code", None)
    if status_code == 429 or type(error).__name__ == "RateLimitError":
        raise RateLimitError(
            provider=provider_name,
            retry_after=extract_retry_delay(error),
            quota_details={"message": str(error)},
        ) from error

    retriable = bool(isinstance(status_code, int) and status_code >= 500)
    raise ProviderError(
        f"Claude direct API error: {error}",
        provider=provider_name,
        retriable=retriable,
        status_code=status_code if isinstance(status_code, int) else None,
    ) from error


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
    """Complete using direct Anthropic API with OAuth token or API key."""
    start_time = time.time()
    credential, cred_type = await resolve_direct_credentials()
    api_model = _resolve_model(model, cred_type, api_model_map)

    system_text, api_messages = convert_messages(messages)
    create_kwargs = _build_create_kwargs(
        api_model, api_messages, system_text,
        max_tokens or get_max_output_tokens(model), temperature, cache_retention,
    )
    _apply_optional_create_kwargs(create_kwargs, kwargs)

    client = _build_client(credential, cred_type)
    try:
        try:
            response = await _create_with_temperature_retry(client, create_kwargs)
        except ProviderError:
            raise
        except Exception as error:
            _raise_direct_api_error(error, provider_name)
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
    """Stream using direct Anthropic API with OAuth token or API key."""
    credential, cred_type = await resolve_direct_credentials()
    api_model = _resolve_model(model, cred_type, api_model_map)

    system_text, api_messages = convert_messages(messages)
    create_kwargs = _build_create_kwargs(
        api_model, api_messages, system_text,
        max_tokens or get_max_output_tokens(model), temperature, cache_retention,
    )
    _apply_optional_create_kwargs(create_kwargs, kwargs)

    abort_event: asyncio.Event | None = kwargs.get("abort_event")

    client = _build_client(credential, cred_type)
    try:
        async for event in _stream_events(client, create_kwargs, abort_event):
            yield event
    except Exception as e:
        logger.error("Claude direct API stream error: %s", e)
        yield StreamEvent(type="error", error=str(e))
    finally:
        await client.close()
