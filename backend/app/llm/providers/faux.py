"""Faux provider — port of pi-mono ``providers/faux.ts``.

Test-double provider that registers under a configurable ``api`` string,
yields scripted responses with realistic streaming-delta cadence (and
optional ``tokens_per_second`` throttling), and persists a per-session
prompt cache so ``cache_read`` / ``cache_write`` reflect realistic usage
math.

Replaces ad-hoc per-test mocking across ``backend/tests/`` (per
convergence-map.md Part B6 — NEW-REQUIREMENT-style port).

Usage pattern (mirrors pi-mono):

    reg = register_faux_provider(api="faux-anthropic-messages")
    reg.set_responses([
        faux_assistant_message("hello"),
        faux_assistant_message([faux_tool_call("echo", {"text": "x"})], stop_reason="toolUse"),
    ])
    model = reg.get_model()
    stream_handle = stream(model, Context(messages=[...]))
    ...
    reg.unregister()
"""

from __future__ import annotations

import asyncio
import copy
import json
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ..api_registry import register_api_provider, unregister_api_providers
from ..event_stream import AssistantMessageEventStream, create_assistant_message_event_stream
from ..types import (
    AssistantContent,
    AssistantMessage,
    Context,
    DoneEvent,
    ErrorEvent,
    ImageContent,
    Message,
    Model,
    ModelCost,
    SimpleStreamOptions,
    StartEvent,
    StopReason,
    StreamOptions,
    TextContent,
    TextDeltaEvent,
    TextEndEvent,
    TextStartEvent,
    ThinkingContent,
    ThinkingDeltaEvent,
    ThinkingEndEvent,
    ThinkingStartEvent,
    ToolCall,
    ToolCallDeltaEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    ToolResultMessage,
    Usage,
    UsageCost,
    UserMessage,
)

__all__ = [
    "FauxModelDefinition",
    "FauxProviderRegistration",
    "RegisterFauxProviderOptions",
    "faux_assistant_message",
    "faux_text",
    "faux_thinking",
    "faux_tool_call",
    "register_faux_provider",
]


_DEFAULT_API = "faux"
_DEFAULT_PROVIDER = "faux"
_DEFAULT_MODEL_ID = "faux-1"
_DEFAULT_MODEL_NAME = "Faux Model"
_DEFAULT_BASE_URL = "http://localhost:0"
_DEFAULT_MIN_TOKEN_SIZE = 3
_DEFAULT_MAX_TOKEN_SIZE = 5


def _default_usage() -> Usage:
    return Usage()


FauxContentBlock = TextContent | ThinkingContent | ToolCall


def faux_text(text: str) -> TextContent:
    return TextContent(text=text)


def faux_thinking(thinking: str) -> ThinkingContent:
    return ThinkingContent(thinking=thinking)


def faux_tool_call(
    name: str,
    arguments: dict[str, Any],
    id: str | None = None,
) -> ToolCall:
    return ToolCall(id=id or _random_id("tool"), name=name, arguments=arguments)


def faux_assistant_message(
    content: str | FauxContentBlock | list[FauxContentBlock],
    *,
    stop_reason: StopReason = "stop",
    error_message: str | None = None,
    response_id: str | None = None,
    timestamp: int | None = None,
) -> AssistantMessage:
    normalized: list[AssistantContent]
    if isinstance(content, str):
        normalized = [faux_text(content)]
    elif isinstance(content, list):
        normalized = list(content)
    else:
        normalized = [content]
    return AssistantMessage(
        content=normalized,
        api=_DEFAULT_API,
        provider=_DEFAULT_PROVIDER,
        model=_DEFAULT_MODEL_ID,
        usage=_default_usage(),
        stop_reason=stop_reason,
        error_message=error_message,
        response_id=response_id,
        timestamp=timestamp if timestamp is not None else int(time.time() * 1000),
    )


# --- Definitions / typed inputs --------------------------------------------


@dataclass(slots=True)
class FauxModelDefinition:
    id: str
    name: str | None = None
    reasoning: bool = False
    input: list[str] | None = None
    cost: ModelCost | None = None
    context_window: int = 128_000
    max_tokens: int = 16_384


FauxResponseFactory = Callable[
    [Context, StreamOptions | None, dict[str, Any], Model[Any]],
    AssistantMessage | Awaitable[AssistantMessage],
]
FauxResponseStep = AssistantMessage | FauxResponseFactory


@dataclass(slots=True)
class RegisterFauxProviderOptions:
    api: str | None = None
    provider: str | None = None
    models: list[FauxModelDefinition] | None = None
    tokens_per_second: float | None = None
    token_size_min: int = _DEFAULT_MIN_TOKEN_SIZE
    token_size_max: int = _DEFAULT_MAX_TOKEN_SIZE


@dataclass(slots=True)
class FauxProviderRegistration:
    api: str
    models: list[Model[Any]]
    state: dict[str, Any]
    _pending: list[FauxResponseStep]
    _source_id: str

    def get_model(self, model_id: str | None = None) -> Model[Any] | None:
        if model_id is None:
            return self.models[0] if self.models else None
        return next((m for m in self.models if m.id == model_id), None)

    def set_responses(self, responses: list[FauxResponseStep]) -> None:
        self._pending[:] = list(responses)

    def append_responses(self, responses: list[FauxResponseStep]) -> None:
        self._pending.extend(responses)

    def get_pending_response_count(self) -> int:
        return len(self._pending)

    def unregister(self) -> None:
        unregister_api_providers(self._source_id)


# --- Internals --------------------------------------------------------------


def _random_id(prefix: str) -> str:
    return f"{prefix}:{int(time.time() * 1000)}:{random.random():.6f}"[2:]


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4) if text else 0


def _content_to_text(content: str | list[TextContent | ImageContent]) -> str:
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, TextContent):
            parts.append(block.text)
        elif isinstance(block, ImageContent):
            parts.append(f"[image:{block.mime_type}:{len(block.data)}]")
    return "\n".join(parts)


def _assistant_content_to_text(content: list[AssistantContent]) -> str:
    parts: list[str] = []
    for block in content:
        if isinstance(block, TextContent):
            parts.append(block.text)
        elif isinstance(block, ThinkingContent):
            parts.append(block.thinking)
        elif isinstance(block, ToolCall):
            parts.append(f"{block.name}:{json.dumps(block.arguments)}")
    return "\n".join(parts)


def _tool_result_to_text(message: ToolResultMessage) -> str:
    parts = [message.tool_name]
    for block in message.content:
        if isinstance(block, TextContent):
            parts.append(block.text)
        elif isinstance(block, ImageContent):
            parts.append(f"[image:{block.mime_type}:{len(block.data)}]")
    return "\n".join(parts)


def _message_to_text(message: Message) -> str:
    if isinstance(message, UserMessage):
        return _content_to_text(message.content)
    if isinstance(message, AssistantMessage):
        return _assistant_content_to_text(message.content)
    return _tool_result_to_text(message)


def _serialize_context(context: Context) -> str:
    parts: list[str] = []
    if context.system_prompt:
        parts.append(f"system:{context.system_prompt}")
    for message in context.messages:
        parts.append(f"{message.role}:{_message_to_text(message)}")
    if context.tools:
        parts.append(f"tools:{json.dumps([{'name': t.name} for t in context.tools])}")
    return "\n\n".join(parts)


def _common_prefix_length(a: str, b: str) -> int:
    length = min(len(a), len(b))
    i = 0
    while i < length and a[i] == b[i]:
        i += 1
    return i


def _with_usage_estimate(
    message: AssistantMessage,
    context: Context,
    options: StreamOptions | None,
    prompt_cache: dict[str, str],
) -> AssistantMessage:
    prompt_text = _serialize_context(context)
    prompt_tokens = _estimate_tokens(prompt_text)
    output_tokens = _estimate_tokens(_assistant_content_to_text(message.content))
    input_tokens = prompt_tokens
    cache_read = 0
    cache_write = 0
    session_id = options.session_id if options else None
    if session_id and (not options or options.cache_retention != "none"):
        previous = prompt_cache.get(session_id)
        if previous:
            cached_chars = _common_prefix_length(previous, prompt_text)
            cache_read = _estimate_tokens(previous[:cached_chars])
            cache_write = _estimate_tokens(prompt_text[cached_chars:])
            input_tokens = max(0, prompt_tokens - cache_read)
        else:
            cache_write = prompt_tokens
        prompt_cache[session_id] = prompt_text

    message.usage = Usage(
        input=input_tokens,
        output=output_tokens,
        cache_read=cache_read,
        cache_write=cache_write,
        total_tokens=input_tokens + output_tokens + cache_read + cache_write,
    )
    message.usage.cost = UsageCost()
    return message


def _split_by_token_size(text: str, min_size: int, max_size: int) -> list[str]:
    if not text:
        return [""]
    chunks: list[str] = []
    index = 0
    while index < len(text):
        token_size = random.randint(min_size, max_size)
        char_size = max(1, token_size * 4)
        chunks.append(text[index : index + char_size])
        index += char_size
    return chunks or [""]


def _clone_message(message: AssistantMessage, api: str, provider: str, model_id: str) -> AssistantMessage:
    cloned = copy.deepcopy(message)
    cloned.api = api
    cloned.provider = provider
    cloned.model = model_id
    if not cloned.timestamp:
        cloned.timestamp = int(time.time() * 1000)
    return cloned


def _error_message(error: Any, api: str, provider: str, model_id: str) -> AssistantMessage:
    return AssistantMessage(
        content=[],
        api=api,
        provider=provider,
        model=model_id,
        usage=_default_usage(),
        stop_reason="error",
        error_message=str(error) if not isinstance(error, BaseException) else (str(error) or type(error).__name__),
        timestamp=int(time.time() * 1000),
    )


def _aborted_message(partial: AssistantMessage) -> AssistantMessage:
    return AssistantMessage(
        content=list(partial.content),
        api=partial.api,
        provider=partial.provider,
        model=partial.model,
        usage=partial.usage,
        stop_reason="aborted",
        error_message="Request was aborted",
        timestamp=int(time.time() * 1000),
    )


async def _schedule_chunk(chunk: str, tokens_per_second: float | None) -> None:
    if not tokens_per_second or tokens_per_second <= 0:
        await asyncio.sleep(0)
        return
    delay = _estimate_tokens(chunk) / tokens_per_second
    await asyncio.sleep(delay)


async def _stream_with_deltas(
    stream: AssistantMessageEventStream,
    message: AssistantMessage,
    min_token_size: int,
    max_token_size: int,
    tokens_per_second: float | None,
    signal: asyncio.Event | None,
) -> None:
    partial = AssistantMessage(
        content=[],
        api=message.api,
        provider=message.provider,
        model=message.model,
        usage=message.usage,
        stop_reason=message.stop_reason,
        timestamp=message.timestamp,
    )

    if signal is not None and signal.is_set():
        aborted = _aborted_message(partial)
        stream.push(ErrorEvent(reason="aborted", error=aborted))
        stream.end(aborted)
        return

    stream.push(StartEvent(partial=partial))

    for index, block in enumerate(message.content):
        if signal is not None and signal.is_set():
            aborted = _aborted_message(partial)
            stream.push(ErrorEvent(reason="aborted", error=aborted))
            stream.end(aborted)
            return

        if isinstance(block, ThinkingContent):
            partial.content.append(ThinkingContent(thinking=""))
            stream.push(ThinkingStartEvent(content_index=index, partial=partial))
            for chunk in _split_by_token_size(block.thinking, min_token_size, max_token_size):
                await _schedule_chunk(chunk, tokens_per_second)
                if signal is not None and signal.is_set():
                    aborted = _aborted_message(partial)
                    stream.push(ErrorEvent(reason="aborted", error=aborted))
                    stream.end(aborted)
                    return
                target = partial.content[index]
                assert isinstance(target, ThinkingContent)
                target.thinking += chunk
                stream.push(
                    ThinkingDeltaEvent(content_index=index, delta=chunk, partial=partial)
                )
            stream.push(
                ThinkingEndEvent(content_index=index, content=block.thinking, partial=partial)
            )
            continue

        if isinstance(block, TextContent):
            partial.content.append(TextContent(text=""))
            stream.push(TextStartEvent(content_index=index, partial=partial))
            for chunk in _split_by_token_size(block.text, min_token_size, max_token_size):
                await _schedule_chunk(chunk, tokens_per_second)
                if signal is not None and signal.is_set():
                    aborted = _aborted_message(partial)
                    stream.push(ErrorEvent(reason="aborted", error=aborted))
                    stream.end(aborted)
                    return
                target = partial.content[index]
                assert isinstance(target, TextContent)
                target.text += chunk
                stream.push(TextDeltaEvent(content_index=index, delta=chunk, partial=partial))
            stream.push(TextEndEvent(content_index=index, content=block.text, partial=partial))
            continue

        # ToolCall
        partial.content.append(ToolCall(id=block.id, name=block.name, arguments={}))
        stream.push(ToolCallStartEvent(content_index=index, partial=partial))
        args_json = json.dumps(block.arguments)
        for chunk in _split_by_token_size(args_json, min_token_size, max_token_size):
            await _schedule_chunk(chunk, tokens_per_second)
            if signal is not None and signal.is_set():
                aborted = _aborted_message(partial)
                stream.push(ErrorEvent(reason="aborted", error=aborted))
                stream.end(aborted)
                return
            stream.push(ToolCallDeltaEvent(content_index=index, delta=chunk, partial=partial))
        target = partial.content[index]
        assert isinstance(target, ToolCall)
        target.arguments = block.arguments
        stream.push(ToolCallEndEvent(content_index=index, tool_call=block, partial=partial))

    if message.stop_reason in ("error", "aborted"):
        reason: Any = message.stop_reason
        stream.push(ErrorEvent(reason=reason, error=message))
        stream.end(message)
        return

    done_reason: Any = message.stop_reason if message.stop_reason in ("stop", "length", "toolUse") else "stop"
    stream.push(DoneEvent(reason=done_reason, message=message))
    stream.end(message)


# --- Public registration ---------------------------------------------------


def register_faux_provider(
    options: RegisterFauxProviderOptions | None = None,
) -> FauxProviderRegistration:
    options = options or RegisterFauxProviderOptions()
    api = options.api or _random_id(_DEFAULT_API)
    provider = options.provider or _DEFAULT_PROVIDER
    source_id = _random_id("faux-provider")

    min_size = max(1, min(options.token_size_min, options.token_size_max))
    max_size = max(min_size, options.token_size_max)
    tokens_per_second = options.tokens_per_second

    state: dict[str, Any] = {"call_count": 0}
    pending: list[FauxResponseStep] = []
    prompt_cache: dict[str, str] = {}

    definitions = options.models or [
        FauxModelDefinition(
            id=_DEFAULT_MODEL_ID,
            name=_DEFAULT_MODEL_NAME,
            reasoning=False,
            input=["text", "image"],
            cost=ModelCost(input=0, output=0, cache_read=0, cache_write=0),
            context_window=128_000,
            max_tokens=16_384,
        )
    ]

    models: list[Model[Any]] = []
    for definition in definitions:
        models.append(
            Model[Any](
                id=definition.id,
                name=definition.name or definition.id,
                api=api,
                provider=provider,
                base_url=_DEFAULT_BASE_URL,
                reasoning=definition.reasoning,
                input=definition.input or ["text", "image"],
                cost=definition.cost or ModelCost(input=0, output=0, cache_read=0, cache_write=0),
                context_window=definition.context_window,
                max_tokens=definition.max_tokens,
            )
        )

    def _stream(
        request_model: Model[Any],
        context: Context,
        stream_options: StreamOptions | None = None,
    ) -> AssistantMessageEventStream:
        outer = create_assistant_message_event_stream()
        state["call_count"] = state["call_count"] + 1
        step = pending.pop(0) if pending else None

        async def runner() -> None:
            try:
                if step is None:
                    message = _error_message(
                        Exception("No more faux responses queued"), api, provider, request_model.id
                    )
                    message = _with_usage_estimate(message, context, stream_options, prompt_cache)
                    outer.push(ErrorEvent(reason="error", error=message))
                    outer.end(message)
                    return

                if callable(step):
                    resolved = step(context, stream_options, state, request_model)
                    if asyncio.iscoroutine(resolved):
                        resolved = await resolved
                else:
                    resolved = step

                assert isinstance(resolved, AssistantMessage)
                message = _clone_message(resolved, api, provider, request_model.id)
                message = _with_usage_estimate(message, context, stream_options, prompt_cache)
                await _stream_with_deltas(
                    outer,
                    message,
                    min_size,
                    max_size,
                    tokens_per_second,
                    stream_options.signal if stream_options else None,
                )
            except Exception as exc:
                message = _error_message(exc, api, provider, request_model.id)
                outer.push(ErrorEvent(reason="error", error=message))
                outer.end(message)

        runner_task = asyncio.create_task(runner())
        outer._faux_runner_task = runner_task  # type: ignore[attr-defined]
        return outer

    def _stream_simple(
        request_model: Model[Any],
        context: Context,
        stream_options: SimpleStreamOptions | None = None,
    ) -> AssistantMessageEventStream:
        return _stream(request_model, context, stream_options)

    class _FauxProvider:
        def __init__(self) -> None:
            self.api = api

        def stream(
            self,
            request_model: Model[Any],
            context: Context,
            stream_options: StreamOptions | None = None,
        ) -> AssistantMessageEventStream:
            return _stream(request_model, context, stream_options)

        def stream_simple(
            self,
            request_model: Model[Any],
            context: Context,
            stream_options: SimpleStreamOptions | None = None,
        ) -> AssistantMessageEventStream:
            return _stream_simple(request_model, context, stream_options)

    register_api_provider(_FauxProvider(), source_id)

    return FauxProviderRegistration(
        api=api,
        models=models,
        state=state,
        _pending=pending,
        _source_id=source_id,
    )
