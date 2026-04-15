"""Private helpers for OpenAI-compatible adapter.

Not part of the public API — import from openai_compat instead.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, Any

from app.adapters.base import CompletionResult, Message, ProviderError, StreamEvent, ToolCallResult

if TYPE_CHECKING:
    from openai import AsyncOpenAI, AsyncStream
    from openai.types.chat import ChatCompletion, ChatCompletionChunk
    from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall

logger = logging.getLogger(__name__)


def _image_data_uri(source: object) -> str | None:
    """Return a data URI for an internal image block source."""
    if not isinstance(source, dict):
        return None
    media_type = source.get("media_type")
    data = source.get("data")
    if not isinstance(media_type, str) or not isinstance(data, str) or not data:
        return None
    return f"data:{media_type};base64,{data}"


def _chat_content_block(block: object) -> dict[str, Any] | None:
    """Convert one internal content block to OpenAI chat-completions format."""
    if not isinstance(block, dict):
        return None
    block_type = block.get("type")
    if block_type == "text":
        text = block.get("text")
        return {"type": "text", "text": str(text) if text is not None else ""}
    if block_type == "image":
        data_uri = _image_data_uri(block.get("source"))
        if data_uri is None:
            return None
        return {"type": "image_url", "image_url": {"url": data_uri}}
    return None


def _responses_content_block(role: str, block: object) -> dict[str, Any] | None:
    """Convert one internal content block to Responses API format."""
    if not isinstance(block, dict):
        return None
    block_type = block.get("type")
    if block_type == "text":
        text = block.get("text")
        return {
            "type": "output_text" if role == "assistant" else "input_text",
            "text": str(text) if text is not None else "",
        }
    if block_type == "image":
        data_uri = _image_data_uri(block.get("source"))
        if data_uri is None:
            return None
        return {"type": "input_image", "image_url": data_uri}
    return None


def normalize_chat_content(content: str | list[dict[str, Any]]) -> str | list[dict[str, Any]]:
    """Convert internal content to OpenAI chat-completions content."""
    if isinstance(content, str):
        return content
    normalized = [
        converted
        for block in content
        if (converted := _chat_content_block(block)) is not None
    ]
    return normalized


def normalize_responses_content(
    role: str,
    content: str | list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert internal content to Responses API content items."""
    if isinstance(content, str):
        block_type = "output_text" if role == "assistant" else "input_text"
        return [{"type": block_type, "text": content}]
    return [
        converted
        for block in content
        if (converted := _responses_content_block(role, block)) is not None
    ]


def is_auth_error(error: Exception) -> bool:
    """Return True when the provider error looks like authentication."""
    message = str(error).lower()
    return "401" in message or "authentication" in message or "unauthorized" in message


async def load_credentials_from_db(provider_name: str) -> str | None:
    """Reload credentials from the database and return the provider key."""
    try:
        from app.db import async_session
        from app.services.credential_manager import get_credential_manager

        cm = get_credential_manager()
        async with async_session() as db:
            await cm.load(db)
        return cm.get_api_key(provider_name)
    except Exception:
        logger.debug("DB credential reload failed for %s", provider_name, exc_info=True)
        return None


def build_assistant_tool_message(result: CompletionResult) -> dict[str, Any]:
    """Build the assistant message dict with tool_calls for conversation history."""
    tool_calls = result.tool_calls or []
    return {
        "role": "assistant",
        "content": result.content or None,
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": json.dumps(tc.input)},
            }
            for tc in tool_calls
        ],
    }


async def execute_tool_calls(
    result: CompletionResult,
    openai_messages: list[dict[str, Any]],
    tool_handler: Callable[[str, dict[str, Any]], Awaitable[str]],
) -> AsyncIterator[StreamEvent]:
    """Execute all tool calls from a result, appending messages and yielding events."""
    openai_messages.append(build_assistant_tool_message(result))
    if result.content:
        yield StreamEvent(type="content", content=result.content)
    for tc in result.tool_calls or []:
        yield StreamEvent(type="tool_use", tool_id=tc.id, tool_name=tc.name, tool_input=tc.input)
        tool_result_str = await tool_handler(tc.name, tc.input)
        yield StreamEvent(type="tool_result", tool_id=tc.id, content=tool_result_str)
        openai_messages.append({"role": "tool", "tool_call_id": tc.id, "content": tool_result_str})


def _to_openai_tool(tool: dict[str, Any]) -> dict[str, Any]:
    """Convert internal tool dict to OpenAI function-calling format.

    Internal format:  ``{"name": ..., "description": ..., "input_schema": ...}``
    OpenAI format:    ``{"type": "function", "function": {"name": ..., "parameters": ...}}``

    If the tool is already in OpenAI format, pass it through unchanged.
    """
    if tool.get("type") == "function" and "function" in tool:
        return tool
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("input_schema") or tool.get("parameters") or {"type": "object", "properties": {}},
        },
    }


def parse_tool_call(tc: Any) -> ToolCallResult:
    """Parse a single OpenAI tool call object into ToolCallResult."""
    try:
        args = json.loads(tc.function.arguments)
    except json.JSONDecodeError:
        args = {}
    return ToolCallResult(
        id=tc.id,
        name=tc.function.name,
        input=args,
        caller_type="native",
        original_id=tc.id,
    )


def _apply_optional_params(params: dict[str, Any], kwargs: dict[str, Any]) -> None:
    """Mutate params with optional keys from kwargs when present."""
    if kwargs.get("tools"):
        params["tools"] = [_to_openai_tool(t) for t in kwargs["tools"]]
    if kwargs.get("tool_choice"):
        params["tool_choice"] = kwargs["tool_choice"]
    if kwargs.get("response_format"):
        params["response_format"] = kwargs["response_format"]
    if kwargs.get("reasoning_effort"):
        params["reasoning_effort"] = kwargs["reasoning_effort"]
    if kwargs.get("extra_headers"):
        params["extra_headers"] = kwargs["extra_headers"]


def build_completion_params(
    model_id: str,
    openai_messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int | None,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Build the params dict for a chat completion request."""
    params: dict[str, Any] = {
        "model": model_id,
        "messages": openai_messages,
        "temperature": temperature,
    }
    if max_tokens:
        params["max_tokens"] = max_tokens
    _apply_optional_params(params, kwargs)
    return params


def build_stream_params(
    model_id: str,
    openai_messages: list[dict[str, Any]],
    temperature: float,
    max_tokens: int | None,
    kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the params dict for a streaming chat completion request."""
    params = build_completion_params(model_id, openai_messages, temperature, max_tokens, kwargs or {})
    params["stream"] = True
    return params


def parse_completion_response(response: ChatCompletion, provider_name: str) -> CompletionResult:
    """Convert an OpenAI chat completion response to CompletionResult."""
    choice = response.choices[0]
    # Some providers return non-string content (e.g. Cloudflare may return int).
    # Reasoning models (qwen3, deepseek-r1) put output in reasoning_content with content=None.
    raw_content = choice.message.content
    reasoning = getattr(choice.message, "reasoning_content", None)
    if raw_content is None and reasoning:
        raw_content = reasoning
    content = str(raw_content) if raw_content is not None else ""
    tool_calls = [parse_tool_call(tc) for tc in choice.message.tool_calls] if choice.message.tool_calls else None
    return CompletionResult(
        content=content,
        model=response.model,
        provider=provider_name,
        input_tokens=response.usage.prompt_tokens if response.usage else 0,
        output_tokens=response.usage.completion_tokens if response.usage else 0,
        finish_reason=choice.finish_reason,
        raw_response=response,
        tool_calls=tool_calls,
    )


def _chunk_to_event(chunk: ChatCompletionChunk) -> StreamEvent | None:
    """Convert a stream chunk to a StreamEvent, or None to skip."""
    if not chunk.choices:
        return None
    delta = chunk.choices[0].delta
    if delta.content:
        return StreamEvent(type="content", content=delta.content)
    return None


def _accumulate_tool_delta(
    accumulators: dict[int, dict[str, str]],
    tc_delta: ChoiceDeltaToolCall,
) -> None:
    """Merge a streaming tool-call delta into the accumulators dict."""
    idx = tc_delta.index
    if idx not in accumulators:
        accumulators[idx] = {"id": "", "name": "", "arguments": ""}
    acc = accumulators[idx]
    if tc_delta.id:
        acc["id"] = tc_delta.id
    if tc_delta.function:
        if tc_delta.function.name:
            acc["name"] = tc_delta.function.name
        if tc_delta.function.arguments:
            acc["arguments"] += tc_delta.function.arguments


async def iterate_stream(stream: AsyncStream[ChatCompletionChunk]) -> AsyncIterator[StreamEvent]:
    """Yield StreamEvents from an OpenAI stream, ending with a done event."""
    tool_call_accumulators: dict[int, dict[str, str]] = {}

    async for chunk in stream:
        event = _chunk_to_event(chunk)
        if event is not None:
            yield event
        if chunk.choices:
            delta = chunk.choices[0].delta
            for tc_delta in delta.tool_calls or []:
                _accumulate_tool_delta(tool_call_accumulators, tc_delta)

    for acc in tool_call_accumulators.values():
        try:
            tool_input = json.loads(acc["arguments"])
        except json.JSONDecodeError:
            tool_input = {}
        yield StreamEvent(
            type="tool_use",
            tool_id=acc["id"],
            tool_name=acc["name"],
            tool_input=tool_input,
        )

    yield StreamEvent(type="done")


def resolve_api_key(provider_name: str, explicit_key: str | None) -> str | None:
    """Try CredentialManager for API key if no explicit key provided."""
    if explicit_key:
        return explicit_key
    try:
        from app.services.credential_manager import get_credential_manager

        cm = get_credential_manager()
        if cm.is_initialized:
            return cm.get_api_key(provider_name)
    except Exception:
        logger.debug("Credential manager lookup failed for %s", provider_name, exc_info=True)
    return None


def build_client_kwargs(
    resolved_key: str,
    base_url: str,
    headers: dict[str, str] | None,
    extra_kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Assemble kwargs for constructing an AsyncOpenAI client."""
    client_kwargs: dict[str, Any] = {"api_key": resolved_key, "base_url": base_url}
    if headers:
        client_kwargs["default_headers"] = headers
    client_kwargs.update(extra_kwargs)
    return client_kwargs


def convert_messages(messages: list[Message]) -> list[dict[str, Any]]:
    """Convert internal Message objects to OpenAI-format dicts."""
    return [{"role": msg.role, "content": normalize_chat_content(msg.content)} for msg in messages]


def handle_provider_error(error: Exception, provider_name: str) -> None:
    """Map an exception to a ProviderError and raise it."""
    msg = str(error)
    if "401" in msg or "Authentication" in msg:
        raise ProviderError(msg, provider_name, status_code=401)
    if "429" in msg or "Rate limit" in msg:
        raise ProviderError(msg, provider_name, retriable=True, status_code=429)
    raise ProviderError(msg, provider_name, retriable=True)


async def _single_request(
    client: AsyncOpenAI, params: dict[str, Any], provider_name: str
) -> CompletionResult:
    """Execute one completion request and map errors to ProviderError."""
    try:
        response = await client.chat.completions.create(**params)
        return parse_completion_response(response, provider_name)
    except Exception as e:
        logger.error("%s completion error: %s", provider_name, e)
        handle_provider_error(e, provider_name)
        raise  # Unreachable


async def complete_once(
    client: AsyncOpenAI,
    provider_name: str,
    params: dict[str, Any],
    refresh_credentials: Callable[..., Awaitable[str | None]],
) -> CompletionResult:
    """Execute a single completion request with auth-retry on 401 errors.

    ``refresh_credentials`` is a callable that accepts ``allow_db_reload`` kwarg
    and returns a fresh API key or None.
    """
    try:
        response = await client.chat.completions.create(**params)
        return parse_completion_response(response, provider_name)
    except Exception as e:
        if not is_auth_error(e):
            logger.error("%s completion error: %s", provider_name, e)
            handle_provider_error(e, provider_name)
            raise  # Unreachable
        fresh = await refresh_credentials(allow_db_reload=True)
        if not fresh:
            logger.error("%s completion error: %s", provider_name, e)
            handle_provider_error(e, provider_name)
            raise  # Unreachable
    return await _single_request(client, params, provider_name)
