"""Google Generative AI provider — port of pi-mono ``providers/google.ts``.

Single-file provider for the ``google-generative-ai`` API surface
(Gemini family + Gemma). Vertex variant follows the same shape; add
``google_vertex.py`` only when a catalog entry actually requires it
(per the Phase 2 convergence directive).

Replaces the 13 ``gemini_*`` files in ``backend/app/adapters/``.
"""

from __future__ import annotations

import asyncio
import base64
import itertools
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Literal

from google import genai

from ..api_registry import register_api_provider
from ..env_api_keys import get_env_api_key
from ..event_stream import AssistantMessageEventStream
from ..provider_support.google_shared import (
    GoogleThinkingLevel,
    convert_messages,
    convert_tools,
    is_thinking_part,
    map_stop_reason,
    map_tool_choice,
    retain_thought_signature,
)
from ..simple_options import build_base_options, clamp_reasoning
from ..types import (
    AssistantMessage,
    Context,
    DoneEvent,
    ErrorEvent,
    Model,
    SimpleStreamOptions,
    StartEvent,
    StreamOptions,
    TextContent,
    TextDeltaEvent,
    TextEndEvent,
    TextStartEvent,
    ThinkingBudgets,
    ThinkingContent,
    ThinkingDeltaEvent,
    ThinkingEndEvent,
    ThinkingStartEvent,
    ToolCall,
    ToolCallDeltaEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    Usage,
    UsageCost,
)
from ..utils.sanitize_unicode import sanitize_surrogates

__all__ = [
    "GoogleOptions",
    "google_provider",
    "stream_google",
    "stream_simple_google",
]

logger = logging.getLogger(__name__)


GoogleToolChoice = Literal["auto", "none", "any"]


@dataclass(slots=True)
class GoogleThinking:
    enabled: bool
    budget_tokens: int | None = None  # -1 for dynamic, 0 to disable
    level: GoogleThinkingLevel | None = None


@dataclass(slots=True)
class GoogleOptions(StreamOptions):
    tool_choice: GoogleToolChoice | None = None
    thinking: GoogleThinking | None = None


_tool_call_counter = itertools.count(1)


def _calculate_cost(model: Model[Any], usage: Usage) -> None:
    cost = model.cost
    usage.cost = UsageCost(
        input=usage.input * cost.input / 1_000_000,
        output=usage.output * cost.output / 1_000_000,
        cache_read=usage.cache_read * cost.cache_read / 1_000_000,
        cache_write=0.0,
    )
    usage.cost.total = usage.cost.input + usage.cost.output + usage.cost.cache_read


def _is_gemma4(model_id: str) -> bool:
    return bool(__import__("re").search(r"gemma-?4", model_id.lower()))


def _is_gemini3_pro(model_id: str) -> bool:
    return bool(__import__("re").search(r"gemini-3(?:\.\d+)?-pro", model_id.lower()))


def _is_gemini3_flash(model_id: str) -> bool:
    return bool(__import__("re").search(r"gemini-3(?:\.\d+)?-flash", model_id.lower()))


ClampedThinkingLevel = Literal["minimal", "low", "medium", "high"]


def _disabled_thinking_config(model: Model[Any]) -> dict[str, Any]:
    if _is_gemini3_pro(model.id):
        return {"thinking_level": "LOW"}
    if _is_gemini3_flash(model.id):
        return {"thinking_level": "MINIMAL"}
    if _is_gemma4(model.id):
        return {"thinking_level": "MINIMAL"}
    return {"thinking_budget": 0}


def _get_thinking_level(effort: ClampedThinkingLevel, model: Model[Any]) -> GoogleThinkingLevel:
    if _is_gemini3_pro(model.id):
        return "LOW" if effort in ("minimal", "low") else "HIGH"
    if _is_gemma4(model.id):
        return "MINIMAL" if effort in ("minimal", "low") else "HIGH"
    if effort == "minimal":
        return "MINIMAL"
    if effort == "low":
        return "LOW"
    if effort == "medium":
        return "MEDIUM"
    return "HIGH"


def _get_google_budget(
    model: Model[Any],
    effort: ClampedThinkingLevel,
    custom_budgets: ThinkingBudgets | None,
) -> int:
    if custom_budgets is not None:
        value = getattr(custom_budgets, effort, None)
        if value is not None:
            return int(value)

    if "2.5-pro" in model.id:
        return {"minimal": 128, "low": 2048, "medium": 8192, "high": 32768}[effort]
    if "2.5-flash-lite" in model.id:
        return {"minimal": 512, "low": 2048, "medium": 8192, "high": 24576}[effort]
    if "2.5-flash" in model.id:
        return {"minimal": 128, "low": 2048, "medium": 8192, "high": 24576}[effort]
    return -1


def _create_client(
    model: Model[Any],
    api_key: str | None,
    options_headers: dict[str, str] | None,
) -> genai.Client:
    http_options: dict[str, Any] = {}
    if model.base_url:
        http_options["base_url"] = model.base_url
        http_options["api_version"] = ""
    if model.headers or options_headers:
        merged: dict[str, str] = dict(model.headers or {})
        if options_headers:
            merged.update(options_headers)
        http_options["headers"] = merged

    return genai.Client(api_key=api_key or None, http_options=http_options or None)


def _build_params(
    model: Model[Any],
    context: Context,
    options: GoogleOptions | None,
) -> dict[str, Any]:
    contents = convert_messages(model, context)

    config: dict[str, Any] = {}
    if options is not None:
        if options.temperature is not None:
            config["temperature"] = options.temperature
        if options.max_tokens is not None:
            config["max_output_tokens"] = options.max_tokens

    if context.system_prompt:
        config["system_instruction"] = sanitize_surrogates(context.system_prompt)

    if context.tools:
        tools_payload = convert_tools(context.tools)
        if tools_payload:
            config["tools"] = tools_payload

    if context.tools and options is not None and options.tool_choice:
        config["tool_config"] = {
            "function_calling_config": {"mode": map_tool_choice(options.tool_choice)}
        }

    if (
        model.reasoning
        and options is not None
        and options.thinking is not None
        and options.thinking.enabled
    ):
        tc: dict[str, Any] = {"include_thoughts": True}
        if options.thinking.level is not None:
            tc["thinking_level"] = options.thinking.level
        elif options.thinking.budget_tokens is not None:
            tc["thinking_budget"] = options.thinking.budget_tokens
        config["thinking_config"] = tc
    elif (
        model.reasoning
        and options is not None
        and options.thinking is not None
        and not options.thinking.enabled
    ):
        config["thinking_config"] = _disabled_thinking_config(model)

    return {"model": model.id, "contents": contents, "config": config}


def _update_usage(usage_metadata: Any, model: Model[Any]) -> Usage:
    prompt_tokens = int(getattr(usage_metadata, "prompt_token_count", 0) or 0)
    cached_tokens = int(getattr(usage_metadata, "cached_content_token_count", 0) or 0)
    candidate_tokens = int(getattr(usage_metadata, "candidates_token_count", 0) or 0)
    thought_tokens = int(getattr(usage_metadata, "thoughts_token_count", 0) or 0)
    total_tokens = int(getattr(usage_metadata, "total_token_count", 0) or 0)
    usage = Usage(
        input=prompt_tokens - cached_tokens,
        output=candidate_tokens + thought_tokens,
        cache_read=cached_tokens,
        cache_write=0,
        total_tokens=total_tokens,
    )
    _calculate_cost(model, usage)
    return usage


def stream_google(
    model: Model[Any],
    context: Context,
    options: GoogleOptions | None = None,
) -> AssistantMessageEventStream:
    stream = AssistantMessageEventStream()

    async def runner() -> None:
        output = AssistantMessage(
            content=[],
            api="google-generative-ai",
            provider=model.provider,
            model=model.id,
            usage=Usage(),
            stop_reason="stop",
            timestamp=int(time.time() * 1000),
        )

        current_block: TextContent | ThinkingContent | None = None

        def block_index() -> int:
            return len(output.content) - 1

        def push_end_for(block: TextContent | ThinkingContent) -> None:
            idx = block_index()
            if isinstance(block, TextContent):
                stream.push(TextEndEvent(content_index=idx, content=block.text, partial=output))
            else:
                stream.push(
                    ThinkingEndEvent(content_index=idx, content=block.thinking, partial=output)
                )

        try:
            api_key = (options.api_key if options else None) or get_env_api_key(model.provider) or ""
            client = _create_client(model, api_key, options.headers if options else None)

            params = _build_params(model, context, options)
            if options and options.on_payload is not None:
                maybe = options.on_payload(params, model)
                if asyncio.iscoroutine(maybe):
                    maybe = await maybe
                if isinstance(maybe, dict):
                    params = maybe

            stream.push(StartEvent(partial=output))

            iterator = await client.aio.models.generate_content_stream(**params)

            async for chunk in iterator:
                if options and options.signal is not None and options.signal.is_set():
                    raise asyncio.CancelledError("Request was aborted")

                response_id = getattr(chunk, "response_id", None)
                if response_id and not output.response_id:
                    output.response_id = response_id

                candidates = getattr(chunk, "candidates", None) or []
                if candidates:
                    candidate = candidates[0]
                    content_obj = getattr(candidate, "content", None)
                    parts = getattr(content_obj, "parts", None) if content_obj else None
                    if parts:
                        for part in parts:
                            part_dict = _part_to_dict(part)
                            text_value = part_dict.get("text")
                            function_call = part_dict.get("function_call")
                            thought_signature = part_dict.get("thought_signature")

                            if text_value is not None:
                                is_thinking = is_thinking_part(part_dict)
                                if (
                                    current_block is None
                                    or (is_thinking and not isinstance(current_block, ThinkingContent))
                                    or (not is_thinking and not isinstance(current_block, TextContent))
                                ):
                                    if current_block is not None:
                                        push_end_for(current_block)
                                    if is_thinking:
                                        current_block = ThinkingContent(thinking="")
                                        output.content.append(current_block)
                                        stream.push(
                                            ThinkingStartEvent(
                                                content_index=block_index(), partial=output
                                            )
                                        )
                                    else:
                                        current_block = TextContent(text="")
                                        output.content.append(current_block)
                                        stream.push(
                                            TextStartEvent(
                                                content_index=block_index(), partial=output
                                            )
                                        )

                                if isinstance(current_block, ThinkingContent):
                                    current_block.thinking += text_value
                                    current_block.thinking_signature = retain_thought_signature(
                                        current_block.thinking_signature, thought_signature
                                    )
                                    stream.push(
                                        ThinkingDeltaEvent(
                                            content_index=block_index(),
                                            delta=text_value,
                                            partial=output,
                                        )
                                    )
                                else:
                                    current_block.text += text_value
                                    current_block.text_signature = retain_thought_signature(
                                        current_block.text_signature, thought_signature
                                    )
                                    stream.push(
                                        TextDeltaEvent(
                                            content_index=block_index(),
                                            delta=text_value,
                                            partial=output,
                                        )
                                    )

                            if function_call:
                                if current_block is not None:
                                    push_end_for(current_block)
                                    current_block = None

                                provided_id = function_call.get("id")
                                needs_new_id = (not provided_id) or any(
                                    isinstance(b, ToolCall) and b.id == provided_id
                                    for b in output.content
                                )
                                tool_call_id = (
                                    f"{function_call.get('name', '')}_{int(time.time() * 1000)}_{next(_tool_call_counter)}"
                                    if needs_new_id
                                    else provided_id
                                )

                                tc = ToolCall(
                                    id=tool_call_id,
                                    name=function_call.get("name", "") or "",
                                    arguments=function_call.get("args") or {},
                                    thought_signature=thought_signature,
                                )
                                output.content.append(tc)
                                stream.push(ToolCallStartEvent(content_index=block_index(), partial=output))
                                stream.push(
                                    ToolCallDeltaEvent(
                                        content_index=block_index(),
                                        delta=json.dumps(tc.arguments),
                                        partial=output,
                                    )
                                )
                                stream.push(
                                    ToolCallEndEvent(
                                        content_index=block_index(),
                                        tool_call=tc,
                                        partial=output,
                                    )
                                )

                    finish_reason = getattr(candidate, "finish_reason", None)
                    if finish_reason:
                        output.stop_reason = map_stop_reason(finish_reason)
                        if any(isinstance(b, ToolCall) for b in output.content):
                            output.stop_reason = "toolUse"

                usage_metadata = getattr(chunk, "usage_metadata", None)
                if usage_metadata is not None:
                    output.usage = _update_usage(usage_metadata, model)

            if current_block is not None:
                push_end_for(current_block)

            if options and options.signal is not None and options.signal.is_set():
                raise asyncio.CancelledError("Request was aborted")
            if output.stop_reason in ("aborted", "error"):
                raise RuntimeError(output.error_message or "An unknown error occurred")

            done_reason = output.stop_reason if output.stop_reason in ("stop", "length", "toolUse") else "stop"
            stream.push(DoneEvent(reason=done_reason, message=output))
            stream.end()
        except asyncio.CancelledError as exc:
            output.stop_reason = "aborted"
            output.error_message = str(exc) or "Request was aborted"
            stream.push(ErrorEvent(reason="aborted", error=output))
            stream.end()
        except Exception as exc:
            aborted = bool(options and options.signal is not None and options.signal.is_set())
            output.stop_reason = "aborted" if aborted else "error"
            output.error_message = str(exc) or type(exc).__name__
            stream.push(ErrorEvent(reason=("aborted" if aborted else "error"), error=output))
            stream.end()

    runner_task = asyncio.create_task(runner())
    stream._google_runner_task = runner_task  # type: ignore[attr-defined]
    return stream


def _part_to_dict(part: Any) -> dict[str, Any]:
    """Normalize a Gemini ``Part`` (Pydantic-like) to a plain dict."""

    if isinstance(part, dict):
        out = dict(part)
        if "thought_signature" in out:
            signature = _normalize_thought_signature(out["thought_signature"])
            if signature is None:
                out.pop("thought_signature")
            else:
                out["thought_signature"] = signature
        return out
    out: dict[str, Any] = {}
    for attr in ("text", "thought", "thought_signature", "function_call", "inline_data"):
        value = getattr(part, attr, None)
        if value is not None:
            if attr == "function_call":
                out[attr] = {
                    "name": getattr(value, "name", None),
                    "args": getattr(value, "args", None) or {},
                    "id": getattr(value, "id", None),
                }
            elif attr == "inline_data":
                out[attr] = {
                    "mime_type": getattr(value, "mime_type", None),
                    "data": getattr(value, "data", None),
                }
            elif attr == "thought_signature":
                signature = _normalize_thought_signature(value)
                if signature is not None:
                    out[attr] = signature
            else:
                out[attr] = value
    return out


def _normalize_thought_signature(value: Any) -> str | None:
    """Keep universal history string-based while preserving Google SDK bytes exactly."""

    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    return None


def stream_simple_google(
    model: Model[Any],
    context: Context,
    options: SimpleStreamOptions | None = None,
) -> AssistantMessageEventStream:
    if options is None:
        options = SimpleStreamOptions()
    api_key = options.api_key or get_env_api_key(model.provider)
    if not api_key:
        raise RuntimeError(f"No API key for provider: {model.provider}")

    base = build_base_options(model, options, api_key)
    if options.reasoning is None:
        return stream_google(
            model,
            context,
            GoogleOptions(
                temperature=base.temperature,
                max_tokens=base.max_tokens,
                signal=base.signal,
                api_key=base.api_key,
                transport=base.transport,
                cache_retention=base.cache_retention,
                session_id=base.session_id,
                on_payload=base.on_payload,
                on_response=base.on_response,
                headers=base.headers,
                timeout_ms=base.timeout_ms,
                max_retries=base.max_retries,
                max_retry_delay_ms=base.max_retry_delay_ms,
                metadata=base.metadata,
                thinking=GoogleThinking(enabled=False),
            ),
        )

    clamped = clamp_reasoning(options.reasoning)
    effort: ClampedThinkingLevel
    if clamped == "minimal":
        effort = "minimal"
    elif clamped == "low":
        effort = "low"
    elif clamped == "medium":
        effort = "medium"
    else:
        effort = "high"

    if _is_gemini3_pro(model.id) or _is_gemini3_flash(model.id) or _is_gemma4(model.id):
        return stream_google(
            model,
            context,
            GoogleOptions(
                temperature=base.temperature,
                max_tokens=base.max_tokens,
                signal=base.signal,
                api_key=base.api_key,
                transport=base.transport,
                cache_retention=base.cache_retention,
                session_id=base.session_id,
                on_payload=base.on_payload,
                on_response=base.on_response,
                headers=base.headers,
                timeout_ms=base.timeout_ms,
                max_retries=base.max_retries,
                max_retry_delay_ms=base.max_retry_delay_ms,
                metadata=base.metadata,
                thinking=GoogleThinking(enabled=True, level=_get_thinking_level(effort, model)),
            ),
        )

    return stream_google(
        model,
        context,
        GoogleOptions(
            temperature=base.temperature,
            max_tokens=base.max_tokens,
            signal=base.signal,
            api_key=base.api_key,
            transport=base.transport,
            cache_retention=base.cache_retention,
            session_id=base.session_id,
            on_payload=base.on_payload,
            on_response=base.on_response,
            headers=base.headers,
            timeout_ms=base.timeout_ms,
            max_retries=base.max_retries,
            max_retry_delay_ms=base.max_retry_delay_ms,
            metadata=base.metadata,
            thinking=GoogleThinking(
                enabled=True,
                budget_tokens=_get_google_budget(model, effort, options.thinking_budgets),
            ),
        ),
    )


# --- Registration ----------------------------------------------------------


class _GoogleProvider:
    api: str = "google-generative-ai"

    def stream(
        self,
        model: Model[Any],
        context: Context,
        options: StreamOptions | None = None,
    ) -> AssistantMessageEventStream:
        if isinstance(options, GoogleOptions):
            return stream_google(model, context, options)
        if options is None:
            return stream_google(model, context, None)
        return stream_google(
            model,
            context,
            GoogleOptions(
                temperature=options.temperature,
                max_tokens=options.max_tokens,
                signal=options.signal,
                api_key=options.api_key,
                transport=options.transport,
                cache_retention=options.cache_retention,
                session_id=options.session_id,
                on_payload=options.on_payload,
                on_response=options.on_response,
                headers=options.headers,
                timeout_ms=options.timeout_ms,
                max_retries=options.max_retries,
                max_retry_delay_ms=options.max_retry_delay_ms,
                metadata=options.metadata,
            ),
        )

    def stream_simple(
        self,
        model: Model[Any],
        context: Context,
        options: SimpleStreamOptions | None = None,
    ) -> AssistantMessageEventStream:
        return stream_simple_google(model, context, options)


google_provider = _GoogleProvider()

register_api_provider(google_provider)
