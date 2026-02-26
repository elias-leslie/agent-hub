"""High-level CloudCode PA operations: complete, stream, tool loop, retry.

Internal module — import public API from gemini_cloudcode.py.
"""

from __future__ import annotations

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

_GENERATE_MAX_RETRIES = 3
_GENERATE_RETRY_BASE_DELAY = 2.0
_GENERATE_RETRY_MAX_DELAY = 30.0


def parse_cloudcode_response(
    data: dict[str, Any],
    model: str,
    provider_name: str,
) -> CompletionResult:
    """Parse cloudcode-pa response into CompletionResult."""
    response = data.get("response", data)

    candidates = response.get("candidates", [])
    content = ""
    thinking_content = ""
    tool_calls: list[ToolCallResult] = []
    finish_reason = None

    if candidates:
        candidate = candidates[0]
        finish_reason = candidate.get("finishReason")
        parts = (candidate.get("content") or {}).get("parts", [])

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
    """Non-streaming completion via cloudcode-pa."""
    kwargs = kwargs or {}
    system_instruction, contents = convert_messages_for_cloudcode(messages)
    generation_config = build_generation_config(
        temperature, max_tokens, model, kwargs.get("thinking_level"),
    )
    tools = (
        build_cloudcode_tools(kwargs["tools"]) if kwargs.get("tools") else None
    )

    try:
        data = await client.generate_content(
            model=model,
            contents=contents,
            system_instruction=system_instruction,
            generation_config=generation_config,
            tools=tools,
        )
    except Exception as e:
        raise ProviderError(
            f"CloudCode completion error: {e}",
            provider=provider_name,
            retriable="429" in str(e) or "503" in str(e),
        ) from e
    return parse_cloudcode_response(data, model, provider_name)


async def cloudcode_stream(
    client: CloudCodeClient,
    messages: list[Message],
    model: str,
    temperature: float = 1.0,
    max_tokens: int | None = None,
    provider_name: str = "gemini",
    kwargs: dict[str, Any] | None = None,
) -> AsyncIterator[StreamEvent]:
    """Stream completion via cloudcode-pa SSE."""
    kwargs = kwargs or {}
    system_instruction, contents = convert_messages_for_cloudcode(messages)
    generation_config = build_generation_config(
        temperature, max_tokens, model, kwargs.get("thinking_level"),
    )
    tools = (
        build_cloudcode_tools(kwargs["tools"]) if kwargs.get("tools") else None
    )

    total_content = ""
    input_tokens = 0
    output_tokens = 0
    finish_reason = "STOP"

    try:
        async for chunk in client.stream_generate_content(
            model=model,
            contents=contents,
            system_instruction=system_instruction,
            generation_config=generation_config,
            tools=tools,
        ):
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
                        yield StreamEvent(type="content", content=part["text"])
                    elif part.get("functionCall"):
                        yield _stream_tool_event(part)

            usage = response.get("usageMetadata", {})
            if usage.get("promptTokenCount"):
                input_tokens = usage["promptTokenCount"]
            if usage.get("candidatesTokenCount"):
                output_tokens = usage["candidatesTokenCount"]

        yield StreamEvent(
            type="done",
            input_tokens=input_tokens,
            output_tokens=output_tokens or len(total_content) // 4,
            finish_reason=finish_reason,
        )
    except Exception as e:
        logger.error("CloudCode stream error: %s", e)
        yield StreamEvent(type="error", error=str(e))


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
    )
    session_id = str(uuid.uuid4())

    system_instruction, contents = convert_messages_for_cloudcode(messages)
    cc_tools = build_cloudcode_tools(tools)
    thinking_level = kwargs.get("thinking_level")

    accumulated_text = ""

    try:
        for _ in range(max_turns):
            gen_config = build_generation_config(1.0, max_tokens, model, thinking_level)

            data = await _generate_with_retry(
                client, model, contents, system_instruction, gen_config, cc_tools,
            )

            response = data.get("response", data)
            candidates = response.get("candidates", [])

            if not candidates:
                yield (
                    ToolEvent(type="error", error="Empty response from model"),
                    session_id,
                )
                return

            candidate = candidates[0]
            parts = (candidate.get("content") or {}).get("parts", [])

            text_content, tool_calls = _parse_candidate_parts(parts)

            if text_content:
                accumulated_text += text_content
                yield (
                    ToolEvent(
                        type="assistant",
                        message=ToolMessage(
                            content=[ToolContentBlock(type="text", text=text_content)],
                        ),
                    ),
                    session_id,
                )

            for tc in tool_calls:
                yield _tool_call_event(tc, session_id)

            if not tool_calls:
                yield (
                    ToolEvent(type="result", subtype="success", result=accumulated_text),
                    session_id,
                )
                return

            tool_results, tool_response_parts = await _execute_tools(tool_calls, tool_handler)

            for tc, result in zip(tool_calls, tool_results, strict=True):
                yield (
                    ToolEvent(
                        type="tool_result",
                        content=result.content,
                        tool_use_id=tc.id,
                        is_error=result.is_error,
                        duration_ms=result.duration_ms,
                    ),
                    session_id,
                )

            contents.append({"role": "model", "parts": _build_model_parts(parts)})
            contents.append({"role": "user", "parts": tool_response_parts})

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
        )
    )


async def _generate_with_retry(
    client: CloudCodeClient,
    model: str,
    contents: list[dict[str, Any]],
    system_instruction: dict[str, Any] | None,
    generation_config: dict[str, Any] | None,
    tools: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Call generate_content with retry on transient errors."""
    import asyncio

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
        except RuntimeError as e:
            if not _is_retryable_error(str(e)):
                raise
            last_exc = e
        except httpx.HTTPStatusError as e:
            if not _is_retryable_status(e.response.status_code):
                raise
            last_exc = e
        except (httpx.ConnectError, httpx.ReadTimeout) as e:
            last_exc = e

        delay = min(
            _GENERATE_RETRY_BASE_DELAY * (2**attempt), _GENERATE_RETRY_MAX_DELAY,
        )
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
