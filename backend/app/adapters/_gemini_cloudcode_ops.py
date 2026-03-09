"""High-level CloudCode PA operations: complete, stream, tool loop, retry.

Internal module — import public API from gemini_cloudcode.py.
"""

from __future__ import annotations

import asyncio
import logging
import traceback
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.adapters._gemini_cloudcode_client import CloudCodeClient
from app.adapters._gemini_cloudcode_transforms import (
    build_cloudcode_tools,
    build_generation_config,
    convert_messages_for_cloudcode,
)
from app.adapters.base import CompletionResult, Message, ProviderError, StreamEvent, ToolCallResult
from app.adapters.gemini_events import ToolContentBlock, ToolEvent, ToolMessage
from app.adapters.gemini_utils import _GEMINI_TOOL_NAME_ALIASES
from app.services.tools import ToolCall
from app.services.tools.direct_executor import create_direct_handler

logger = logging.getLogger(__name__)

_GENERATE_MAX_RETRIES = 4
_GENERATE_RETRY_BASE_DELAY = 2.0
_GENERATE_RETRY_MAX_DELAY = 90.0  # Google 429s often suggest 30-45s delays


def _parse_parts_for_response(
    parts: list[dict[str, Any]],
) -> tuple[str, str, list[ToolCallResult]]:
    """Extract text, thinking content, and tool calls from response parts."""
    content = ""
    thinking_content = ""
    tool_calls: list[ToolCallResult] = []

    for part in parts:
        if part.get("thought") and part.get("text"):
            thinking_content += part["text"]
        elif part.get("text"):
            content += part["text"]
        elif part.get("functionCall"):
            fc = part["functionCall"]
            raw_name = fc.get("name", "unknown")
            tool_calls.append(
                ToolCallResult(
                    id=fc.get("id") or raw_name,
                    name=_GEMINI_TOOL_NAME_ALIASES.get(raw_name, raw_name),
                    input=fc.get("args", {}),
                )
            )

    return content, thinking_content, tool_calls


def parse_cloudcode_response(
    data: dict[str, Any],
    model: str,
    provider_name: str,
) -> CompletionResult:
    """Parse cloudcode-pa response into CompletionResult."""
    response = data.get("response", data)
    candidates = response.get("candidates", [])
    finish_reason = None
    content = ""
    thinking_content = ""
    tool_calls: list[ToolCallResult] = []

    if candidates:
        candidate = candidates[0]
        finish_reason = candidate.get("finishReason")
        parts = (candidate.get("content") or {}).get("parts", [])
        content, thinking_content, tool_calls = _parse_parts_for_response(parts)

    usage = response.get("usageMetadata", {})
    input_tokens = usage.get("promptTokenCount", 0) or 0
    output_tokens = usage.get("candidatesTokenCount", 0) or 0
    thoughts_token_count = usage.get("thoughtsTokenCount")
    thinking_tokens = thoughts_token_count or (
        len(thinking_content) // 4 if thinking_content else None
    )

    return CompletionResult(
        content=content,
        model=model,
        provider=provider_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        finish_reason=finish_reason,
        raw_response=data,
        tool_calls=tool_calls if tool_calls else None,
        thinking_content=thinking_content if thinking_content else None,
        thinking_tokens=thinking_tokens,
    )


async def cloudcode_complete(
    client: CloudCodeClient,
    messages: list[Message],
    model: str,
    temperature: float = 1.0,
    max_tokens: int | None = None,
    provider_name: str = "gemini",
    kwargs: dict[str, Any] | None = None,
) -> CompletionResult:
    """Non-streaming completion via cloudcode-pa.

    Retries on 429/5xx using server-delay-aware backoff before giving up.
    """
    kwargs = kwargs or {}
    system_instruction, contents = convert_messages_for_cloudcode(messages)
    generation_config = build_generation_config(
        temperature, max_tokens, model, kwargs.get("thinking_level"),
    )
    tools = (
        build_cloudcode_tools(kwargs["tools"]) if kwargs.get("tools") else None
    )

    try:
        data = await _generate_with_retry(
            client, model, contents, system_instruction, generation_config, tools,
        )
    except Exception as e:
        raise ProviderError(
            f"CloudCode completion error: {e}",
            provider=provider_name,
            retriable="429" in str(e) or "503" in str(e),
        ) from e
    return parse_cloudcode_response(data, model, provider_name)


def _process_stream_chunk(
    chunk: dict[str, Any],
    total_content: str,
    input_tokens: int,
    output_tokens: int,
    finish_reason: str,
    content_yielded: bool,
) -> tuple[str, int, int, str, bool, list[StreamEvent]]:
    """Process a single stream chunk and return updated state plus events to yield."""
    events: list[StreamEvent] = []
    response = chunk.get("response", chunk)
    candidates = response.get("candidates", [])

    if candidates:
        candidate = candidates[0]
        if candidate.get("finishReason"):
            finish_reason = candidate["finishReason"]

        parts = (candidate.get("content") or {}).get("parts", [])
        for part in parts:
            if part.get("text") and not part.get("thought"):
                total_content += part["text"]
                content_yielded = True
                events.append(StreamEvent(type="content", content=part["text"]))
            elif part.get("functionCall"):
                content_yielded = True
                events.append(_stream_tool_event(part))

    usage = response.get("usageMetadata", {})
    if usage.get("promptTokenCount"):
        input_tokens = usage["promptTokenCount"]
    if usage.get("candidatesTokenCount"):
        output_tokens = usage["candidatesTokenCount"]

    return total_content, input_tokens, output_tokens, finish_reason, content_yielded, events


async def _stream_one_attempt(
    client: CloudCodeClient,
    model: str,
    contents: list[dict[str, Any]],
    system_instruction: dict[str, Any] | None,
    generation_config: dict[str, Any] | None,
    tools: list[dict[str, Any]] | None,
) -> AsyncIterator[StreamEvent]:
    """Run a single streaming attempt; yields content/tool events then a done event.

    Raises on error so the caller can decide whether to retry.
    """
    total_content = ""
    input_tokens = 0
    output_tokens = 0
    finish_reason = "STOP"
    content_yielded = False

    async for chunk in client.stream_generate_content(
        model=model,
        contents=contents,
        system_instruction=system_instruction,
        generation_config=generation_config,
        tools=tools,
    ):
        total_content, input_tokens, output_tokens, finish_reason, content_yielded, events = (
            _process_stream_chunk(
                chunk, total_content, input_tokens, output_tokens,
                finish_reason, content_yielded,
            )
        )
        for event in events:
            yield event

    yield StreamEvent(
        type="done",
        input_tokens=input_tokens,
        output_tokens=output_tokens or len(total_content) // 4,
        finish_reason=finish_reason,
    )


async def cloudcode_stream(
    client: CloudCodeClient,
    messages: list[Message],
    model: str,
    temperature: float = 1.0,
    max_tokens: int | None = None,
    provider_name: str = "gemini",
    kwargs: dict[str, Any] | None = None,
) -> AsyncIterator[StreamEvent]:
    """Stream completion via cloudcode-pa SSE.

    Retries on transient errors (429/5xx) if no content has been yielded yet.
    Once content starts flowing, errors are emitted as-is (can't replay partial stream).
    """
    kwargs = kwargs or {}
    system_instruction, contents = convert_messages_for_cloudcode(messages)
    generation_config = build_generation_config(
        temperature, max_tokens, model, kwargs.get("thinking_level"),
    )
    tools = (
        build_cloudcode_tools(kwargs["tools"]) if kwargs.get("tools") else None
    )

    for attempt in range(_GENERATE_MAX_RETRIES):
        content_yielded = False
        retry_after: float | None = None
        try:
            async for event in _stream_one_attempt(
                client, model, contents, system_instruction, generation_config, tools,
            ):
                content_yielded = content_yielded or event.type in ("content", "tool_use")
                yield event
            return
        except Exception as e:
            quota_info = _get_quota_info(e)
            if content_yielded or not _is_retryable(e):
                logger.error("CloudCode stream error: %s%s", e, quota_info)
                yield StreamEvent(type="error", error=str(e))
                return
            retry_after = _compute_retry_delay(e, attempt)
            logger.warning(
                "CloudCode stream retry %d/%d after %s (delay=%.1fs)%s",
                attempt + 1, _GENERATE_MAX_RETRIES, type(e).__name__, retry_after, quota_info,
            )
        await asyncio.sleep(retry_after or _GENERATE_RETRY_BASE_DELAY)

    yield StreamEvent(type="error", error="CloudCode stream retries exhausted")


def _stream_tool_event(part: dict[str, Any]) -> StreamEvent:
    """Build a tool_use StreamEvent from a functionCall part."""
    fc = part["functionCall"]
    raw_name = fc.get("name", "unknown")
    return StreamEvent(
        type="tool_use",
        tool_id=fc.get("id") or f"tool_{uuid.uuid4().hex[:12]}",
        tool_name=_GEMINI_TOOL_NAME_ALIASES.get(raw_name, raw_name),
        tool_input=fc.get("args", {}),
        thought_signature=part.get("thoughtSignature"),
    )


def _make_text_event(text: str, session_id: str) -> tuple[ToolEvent, str]:
    """Build an assistant text ToolEvent."""
    return (
        ToolEvent(
            type="assistant",
            message=ToolMessage(
                content=[ToolContentBlock(type="text", text=text)],
            ),
        ),
        session_id,
    )


def _make_tool_result_events(
    tool_calls: list[ToolCall],
    tool_results: list[Any],
    session_id: str,
) -> list[tuple[ToolEvent, str]]:
    """Build tool_result ToolEvents for each executed tool."""
    return [
        (
            ToolEvent(
                type="tool_result",
                content=result.content,
                tool_use_id=tc.id,
                is_error=result.is_error,
                duration_ms=result.duration_ms,
            ),
            session_id,
        )
        for tc, result in zip(tool_calls, tool_results, strict=True)
    ]


async def _process_tool_loop_turn(
    client: CloudCodeClient,
    model: str,
    contents: list[dict[str, Any]],
    system_instruction: dict[str, Any] | None,
    gen_config: dict[str, Any] | None,
    cc_tools: list[dict[str, Any]],
    tool_handler: Any,
    accumulated_text: str,
    session_id: str,
) -> tuple[str, list[tuple[ToolEvent, str]], bool]:
    """Execute one turn of the tool loop; returns (accumulated_text, events, done)."""
    data = await _generate_with_retry(
        client, model, contents, system_instruction, gen_config, cc_tools,
    )

    response = data.get("response", data)
    candidates = response.get("candidates", [])

    if not candidates:
        return accumulated_text, [(ToolEvent(type="error", error="Empty response from model"), session_id)], True

    candidate = candidates[0]
    parts = (candidate.get("content") or {}).get("parts", [])
    text_content, tool_calls = _parse_candidate_parts(parts)

    events: list[tuple[ToolEvent, str]] = []
    if text_content:
        accumulated_text += text_content
        events.append(_make_text_event(text_content, session_id))

    for tc in tool_calls:
        events.append(_tool_call_event(tc, session_id))

    if not tool_calls:
        events.append((ToolEvent(type="result", subtype="success", result=accumulated_text), session_id))
        return accumulated_text, events, True

    tool_results, tool_response_parts = await _execute_tools(tool_calls, tool_handler)
    events.extend(_make_tool_result_events(tool_calls, tool_results, session_id))

    contents.append({"role": "model", "parts": _build_model_parts(parts)})
    contents.append({"role": "user", "parts": tool_response_parts})

    return accumulated_text, events, False


async def cloudcode_tool_loop(
    client: CloudCodeClient,
    messages: list[Message],
    model: str,
    tools: list[dict[str, Any]],
    working_dir: str | None,
    max_tokens: int | None,
    max_turns: int,
    provider_name: str,
    permission_config: dict[str, Any] | None = None,
    project_id: str | None = None,
    **kwargs: Any,
) -> AsyncIterator[tuple[ToolEvent, str]]:
    """Run agentic tool loop via cloudcode-pa."""
    tool_handler = create_direct_handler(
        working_dir, permission_config, project_id=project_id,
        tool_catalog=kwargs.get("tool_catalog"),
    )
    session_id = str(uuid.uuid4())

    system_instruction, contents = convert_messages_for_cloudcode(messages)
    cc_tools = build_cloudcode_tools(tools)
    thinking_level = kwargs.get("thinking_level")
    accumulated_text = ""

    try:
        for _ in range(max_turns):
            gen_config = build_generation_config(1.0, max_tokens, model, thinking_level)
            accumulated_text, events, done = await _process_tool_loop_turn(
                client, model, contents, system_instruction, gen_config, cc_tools,
                tool_handler, accumulated_text, session_id,
            )
            for event in events:
                yield event
            if done:
                return

        yield (
            ToolEvent(type="result", subtype="success", result=accumulated_text),
            session_id,
        )

    except Exception as e:
        logger.error("CloudCode tool error: %s\n%s", e, traceback.format_exc())
        yield (ToolEvent(type="error", error=str(e)), session_id)


def _parse_candidate_parts(
    parts: list[dict[str, Any]],
) -> tuple[str, list[ToolCall]]:
    """Extract text content and tool calls from candidate parts."""
    text_content = ""
    tool_calls: list[ToolCall] = []

    for part in parts:
        if part.get("text") and not part.get("thought"):
            text_content += part["text"]
        elif part.get("functionCall"):
            fc = part["functionCall"]
            raw_name = fc.get("name", "unknown")
            tool_calls.append(
                ToolCall(
                    id=(fc.get("id") or f"{raw_name}_{uuid.uuid4().hex[:8]}"),
                    name=_GEMINI_TOOL_NAME_ALIASES.get(raw_name, raw_name),
                    input=fc.get("args", {}),
                )
            )

    return text_content, tool_calls


def _tool_call_event(tc: ToolCall, session_id: str) -> tuple[ToolEvent, str]:
    """Build a ToolEvent for a tool_use action."""
    return (
        ToolEvent(
            type="assistant",
            message=ToolMessage(
                content=[
                    ToolContentBlock(
                        type="tool_use",
                        name=tc.name,
                        input=tc.input,
                        id=tc.id,
                    ),
                ],
            ),
        ),
        session_id,
    )


def _build_model_parts(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build model turn parts preserving thoughtSignature for CloudCode PA API."""
    model_parts: list[dict[str, Any]] = []
    for part in parts:
        if part.get("text") and not part.get("thought"):
            model_parts.append({"text": part["text"]})
        elif part.get("thought") and part.get("text"):
            thought_part: dict[str, Any] = {"text": part["text"], "thought": True}
            if part.get("thoughtSignature"):
                thought_part["thoughtSignature"] = part["thoughtSignature"]
            model_parts.append(thought_part)
        elif part.get("functionCall"):
            fc_part: dict[str, Any] = {"functionCall": part["functionCall"]}
            if part.get("thoughtSignature"):
                fc_part["thoughtSignature"] = part["thoughtSignature"]
            model_parts.append(fc_part)
    return model_parts


async def _execute_tools(
    tool_calls: list[ToolCall],
    tool_handler: Any,
) -> tuple[list[Any], list[dict[str, Any]]]:
    """Execute tools, returning (result_objects, functionResponse_parts)."""
    results = []
    tool_response_parts: list[dict[str, Any]] = []
    for tc in tool_calls:
        result = await tool_handler.execute(tc)
        results.append(result)
        tool_response_parts.append({
            "functionResponse": {
                "name": tc.name,
                "id": tc.id,
                "response": {"result": result.content},
            },
        })
    return results, tool_response_parts


def _is_retryable_status(status_code: int) -> bool:
    return status_code in {429, 500, 502, 503, 504}


def _is_retryable_error(text: str) -> bool:
    lower = text.lower()
    return any(
        kw in lower
        for kw in (
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
    )


def _is_retryable(e: Exception) -> bool:
    """Check if any exception is retryable (combines type and string checks)."""
    if isinstance(e, httpx.HTTPStatusError):
        return _is_retryable_status(e.response.status_code)
    if isinstance(e, (httpx.ConnectError, httpx.ReadTimeout)):
        return True
    return _is_retryable_error(str(e))


def _compute_retry_delay(exc: Exception, attempt: int) -> float:
    """Compute delay before next retry, preferring server-requested delay."""
    from app.adapters.errors import extract_retry_delay

    server_delay = extract_retry_delay(exc)
    if server_delay is not None and server_delay > 0:
        return min(server_delay, _GENERATE_RETRY_MAX_DELAY)
    return min(_GENERATE_RETRY_BASE_DELAY * (2**attempt), _GENERATE_RETRY_MAX_DELAY)


async def _generate_with_retry(
    client: CloudCodeClient,
    model: str,
    contents: list[dict[str, Any]],
    system_instruction: dict[str, Any] | None,
    generation_config: dict[str, Any] | None,
    tools: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Call generate_content with retry on transient errors.

    Parses the server's "reset after Xs" hint from 429 responses and
    uses that as the delay instead of a fixed exponential backoff.
    """
    last_exc: Exception | None = None
    for attempt in range(_GENERATE_MAX_RETRIES):
        try:
            return await client.generate_content(
                model=model,
                contents=contents,
                system_instruction=system_instruction,
                generation_config=generation_config,
                tools=tools,
            )
        except Exception as e:
            if not _is_retryable(e):
                raise
            last_exc = e

        delay = _compute_retry_delay(last_exc, attempt)
        quota_info = _get_quota_info(last_exc)
        logger.warning(
            "CloudCode retry %d/%d after %s (delay=%.1fs)%s",
            attempt + 1,
            _GENERATE_MAX_RETRIES,
            type(last_exc).__name__,
            delay,
            quota_info,
        )
        await asyncio.sleep(delay)

    raise last_exc  # type: ignore[misc]


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
        pass
    return ""
