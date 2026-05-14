"""Anthropic Messages-compatible provider.

Single-file provider. Native streaming only (no ``messages.create`` without
``stream=True`` anywhere). This adapter keeps the Anthropic Messages protocol
for compatible providers such as Kimi Code and MiniMax; Agent Hub does not use
Claude/Anthropic as a workload provider.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from anthropic import AsyncAnthropic
from anthropic._exceptions import AnthropicError

from ..api_registry import register_api_provider
from ..env_api_keys import get_env_api_key
from ..event_stream import AssistantMessageEventStream
from ..simple_options import (
    adjust_max_tokens_for_thinking,
    build_base_options,
    clamp_reasoning,
)
from ..transform_messages import transform_messages
from ..types import (
    AnthropicMessagesCompat,
    AssistantContent,
    AssistantMessage,
    CacheRetention,
    Context,
    DoneEvent,
    ErrorEvent,
    ImageContent,
    Message,
    Model,
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
    Tool,
    ToolCall,
    ToolCallDeltaEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    ToolResultMessage,
    Usage,
    UsageCost,
    UserMessage,
)
from ..utils.json_parse import parse_streaming_json
from ..utils.sanitize_unicode import sanitize_surrogates

# Re-export for downstream type-checkers that don't follow the `as` alias.
__all__ = [
    "AnthropicEffort",
    "AnthropicOptions",
    "AnthropicThinkingDisplay",
    "anthropic_provider",
    "stream_anthropic",
    "stream_simple_anthropic",
]

logger = logging.getLogger(__name__)


AnthropicEffort = Literal["low", "medium", "high", "xhigh", "max"]
AnthropicThinkingDisplay = Literal["summarized", "omitted"]


@dataclass(slots=True)
class AnthropicOptions(StreamOptions):
    """Anthropic-specific stream options."""

    thinking_enabled: bool | None = None
    thinking_budget_tokens: int | None = None
    effort: AnthropicEffort | None = None
    thinking_display: AnthropicThinkingDisplay | None = None
    interleaved_thinking: bool | None = None
    tool_choice: str | dict[str, Any] | None = None
    # Pre-built client (Vertex/Bedrock variants). When set, skips internal client construction.
    client: AsyncAnthropic | None = None


_FINE_GRAINED_TOOL_STREAMING_BETA = "fine-grained-tool-streaming-2025-05-14"
_INTERLEAVED_THINKING_BETA = "interleaved-thinking-2025-05-14"


# --- Cache-retention helpers ----------------------------------------------


def _resolve_cache_retention(cache_retention: CacheRetention | None) -> CacheRetention:
    if cache_retention is not None:
        return cache_retention
    if os.environ.get("PI_CACHE_RETENTION") == "long":
        return "long"
    return "short"


@dataclass(slots=True)
class _CacheControl:
    type: Literal["ephemeral"] = "ephemeral"
    ttl: Literal["1h"] | None = None

    def to_payload(self) -> dict[str, Any]:
        out: dict[str, Any] = {"type": self.type}
        if self.ttl:
            out["ttl"] = self.ttl
        return out


@dataclass(slots=True)
class _ResolvedCache:
    retention: CacheRetention
    cache_control: _CacheControl | None = None


def _get_cache_control(model: Model[Any], cache_retention: CacheRetention | None) -> _ResolvedCache:
    retention = _resolve_cache_retention(cache_retention)
    if retention == "none":
        return _ResolvedCache(retention=retention)
    compat = _get_anthropic_compat(model)
    ttl = "1h" if retention == "long" and compat.supports_long_cache_retention else None
    return _ResolvedCache(retention=retention, cache_control=_CacheControl(ttl=ttl))


def _get_anthropic_compat(model: Model[Any]) -> AnthropicMessagesCompat:
    """Resolve effective compat settings (defaults + auto-detected per provider)."""

    is_fireworks = model.provider == "fireworks"

    compat: AnthropicMessagesCompat | None = None
    if isinstance(model.compat, AnthropicMessagesCompat):
        compat = model.compat

    def _or(value: bool | None, default: bool) -> bool:
        return value if value is not None else default

    return AnthropicMessagesCompat(
        supports_eager_tool_input_streaming=_or(
            compat.supports_eager_tool_input_streaming if compat else None,
            not is_fireworks,
        ),
        supports_long_cache_retention=_or(
            compat.supports_long_cache_retention if compat else None,
            not is_fireworks,
        ),
        send_session_affinity_headers=_or(
            compat.send_session_affinity_headers if compat else None,
            is_fireworks,
        ),
        supports_cache_control_on_tools=_or(
            compat.supports_cache_control_on_tools if compat else None,
            not is_fireworks,
        ),
    )


# --- Content-block conversion ---------------------------------------------


_ImageMediaType = Literal["image/jpeg", "image/png", "image/gif", "image/webp"]


def _convert_content_blocks(
    content: list[TextContent | ImageContent],
) -> str | list[dict[str, Any]]:
    """Convert universal content blocks to Anthropic ContentBlockParam."""

    has_images = any(isinstance(c, ImageContent) for c in content)
    if not has_images:
        joined = "\n".join(c.text for c in content if isinstance(c, TextContent))
        return sanitize_surrogates(joined)

    blocks: list[dict[str, Any]] = []
    for block in content:
        if isinstance(block, TextContent):
            blocks.append({"type": "text", "text": sanitize_surrogates(block.text)})
        elif isinstance(block, ImageContent):
            blocks.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": block.mime_type,
                        "data": block.data,
                    },
                }
            )

    has_text = any(b["type"] == "text" for b in blocks)
    if not has_text:
        blocks.insert(0, {"type": "text", "text": "(see attached image)"})
    return blocks


def _normalize_tool_call_id(id_: str, _model: Model[Any], _src: AssistantMessage) -> str:
    """Anthropic tool-call IDs must match ``[a-zA-Z0-9_-]+`` and be ≤64 chars."""

    cleaned = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in id_)
    return cleaned[:64]


# --- Message conversion ---------------------------------------------------


def convert_messages(
    messages: list[Message],
    model: Model[Any],
    cache_control: _CacheControl | None,
) -> list[dict[str, Any]]:
    """Convert universal messages to Anthropic ``MessageParam`` list."""

    transformed = transform_messages(messages, model, _normalize_tool_call_id)
    params: list[dict[str, Any]] = []

    i = 0
    while i < len(transformed):
        msg = transformed[i]

        if isinstance(msg, UserMessage):
            if isinstance(msg.content, str):
                text = sanitize_surrogates(msg.content)
                if text.strip():
                    params.append({"role": "user", "content": text})
            else:
                blocks: list[dict[str, Any]] = []
                for item in msg.content:
                    if isinstance(item, TextContent):
                        blocks.append({"type": "text", "text": sanitize_surrogates(item.text)})
                    elif isinstance(item, ImageContent):
                        blocks.append(
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": item.mime_type,
                                    "data": item.data,
                                },
                            }
                        )
                filtered = [b for b in blocks if b["type"] != "text" or b["text"].strip()]
                if filtered:
                    params.append({"role": "user", "content": filtered})
            i += 1
            continue

        if isinstance(msg, AssistantMessage):
            out_blocks: list[dict[str, Any]] = []
            for block in msg.content:
                if isinstance(block, TextContent):
                    if not block.text.strip():
                        continue
                    out_blocks.append({"type": "text", "text": sanitize_surrogates(block.text)})
                elif isinstance(block, ThinkingContent):
                    if block.redacted:
                        if block.thinking_signature:
                            out_blocks.append(
                                {"type": "redacted_thinking", "data": block.thinking_signature}
                            )
                        continue
                    if not block.thinking.strip():
                        continue
                    # If signature missing/empty (e.g. aborted), demote to text.
                    if not block.thinking_signature or not block.thinking_signature.strip():
                        out_blocks.append({"type": "text", "text": sanitize_surrogates(block.thinking)})
                    else:
                        out_blocks.append(
                            {
                                "type": "thinking",
                                "thinking": sanitize_surrogates(block.thinking),
                                "signature": block.thinking_signature,
                            }
                        )
                elif isinstance(block, ToolCall):
                    out_blocks.append(
                        {
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.arguments or {},
                        }
                    )
            if out_blocks:
                params.append({"role": "assistant", "content": out_blocks})
            i += 1
            continue

        if isinstance(msg, ToolResultMessage):
            tool_results: list[dict[str, Any]] = [
                {
                    "type": "tool_result",
                    "tool_use_id": msg.tool_call_id,
                    "content": _convert_content_blocks(msg.content),
                    "is_error": msg.is_error,
                }
            ]
            j = i + 1
            while j < len(transformed) and isinstance(transformed[j], ToolResultMessage):
                next_msg = transformed[j]
                assert isinstance(next_msg, ToolResultMessage)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": next_msg.tool_call_id,
                        "content": _convert_content_blocks(next_msg.content),
                        "is_error": next_msg.is_error,
                    }
                )
                j += 1
            i = j
            params.append({"role": "user", "content": tool_results})
            continue

        i += 1

    if cache_control and params:
        last = params[-1]
        if last["role"] == "user":
            content = last["content"]
            if isinstance(content, list) and content:
                tail = content[-1]
                if tail.get("type") in ("text", "image", "tool_result"):
                    tail["cache_control"] = cache_control.to_payload()
            elif isinstance(content, str):
                last["content"] = [
                    {"type": "text", "text": content, "cache_control": cache_control.to_payload()}
                ]

    return params


def _convert_tools(
    tools: list[Tool],
    supports_eager_tool_input_streaming: bool,
    cache_control: _CacheControl | None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for index, tool in enumerate(tools):
        schema = tool.parameters or {}
        params: dict[str, Any] = {
            "name": tool.name,
            "description": tool.description,
            "input_schema": {
                "type": "object",
                "properties": schema.get("properties", {}),
                "required": schema.get("required", []),
            },
        }
        if supports_eager_tool_input_streaming:
            params["eager_input_streaming"] = True
        if cache_control and index == len(tools) - 1:
            params["cache_control"] = cache_control.to_payload()
        out.append(params)
    return out


def _supports_adaptive_thinking(model_id: str) -> bool:
    """Opus 4.6+/Sonnet 4.6 use adaptive thinking (model decides)."""

    return (
        "opus-4-6" in model_id
        or "opus-4.6" in model_id
        or "opus-4-7" in model_id
        or "opus-4.7" in model_id
        or "sonnet-4-6" in model_id
        or "sonnet-4.6" in model_id
    )


def _map_thinking_level_to_effort(
    model: Model[Any],
    level: str | None,
) -> AnthropicEffort:
    if level and model.thinking_level_map:
        mapped = model.thinking_level_map.get(level)
        if isinstance(mapped, str) and mapped in ("low", "medium", "high", "xhigh", "max"):
            return mapped
    if level in ("minimal", "low"):
        return "low"
    if level == "medium":
        return "medium"
    return "high"


def build_params(
    model: Model[Any],
    context: Context,
    options: AnthropicOptions | None,
) -> dict[str, Any]:
    """Build the Anthropic ``messages.create`` request body."""

    resolved = _get_cache_control(model, options.cache_retention if options else None)
    cc = resolved.cache_control
    cc_payload = cc.to_payload() if cc else None

    params: dict[str, Any] = {
        "model": model.id,
        "messages": convert_messages(context.messages, model, cc),
        "max_tokens": (options.max_tokens if options and options.max_tokens else (model.max_tokens // 3)),
        "stream": True,
    }

    if context.system_prompt:
        params["system"] = [
            {
                "type": "text",
                "text": sanitize_surrogates(context.system_prompt),
                **({"cache_control": cc_payload} if cc_payload else {}),
            }
        ]

    if options and options.temperature is not None and not options.thinking_enabled:
        params["temperature"] = options.temperature

    if context.tools:
        compat = _get_anthropic_compat(model)
        params["tools"] = _convert_tools(
            context.tools,
            bool(compat.supports_eager_tool_input_streaming),
            cc if compat.supports_cache_control_on_tools else None,
        )

    if model.reasoning and options and options.thinking_enabled:
        display: AnthropicThinkingDisplay = options.thinking_display or "summarized"
        if _supports_adaptive_thinking(model.id):
            params["thinking"] = {"type": "adaptive", "display": display}
            if options.effort:
                params["output_config"] = {"effort": options.effort}
        else:
            params["thinking"] = {
                "type": "enabled",
                "budget_tokens": options.thinking_budget_tokens or 1024,
                "display": display,
            }
    elif model.reasoning and options and options.thinking_enabled is False:
        params["thinking"] = {"type": "disabled"}

    if options and options.metadata:
        user_id = options.metadata.get("user_id")
        if isinstance(user_id, str):
            params["metadata"] = {"user_id": user_id}

    if options and options.tool_choice:
        if isinstance(options.tool_choice, str):
            params["tool_choice"] = {"type": options.tool_choice}
        else:
            params["tool_choice"] = options.tool_choice

    return params


# --- Client construction --------------------------------------------------


def create_client(
    model: Model[Any],
    api_key: str,
    interleaved_thinking: bool,
    use_fine_grained_tool_streaming_beta: bool,
    options_headers: dict[str, str] | None,
    session_id: str | None,
) -> AsyncAnthropic:
    """Return an Anthropic Messages-compatible client for ``model``."""

    needs_interleaved_beta = interleaved_thinking and not _supports_adaptive_thinking(model.id)
    beta_features: list[str] = []
    if use_fine_grained_tool_streaming_beta:
        beta_features.append(_FINE_GRAINED_TOOL_STREAMING_BETA)
    if needs_interleaved_beta:
        beta_features.append(_INTERLEAVED_THINKING_BETA)

    if model.provider == "github-copilot":
        headers = _merge_headers(
            {
                "accept": "application/json",
                **({"anthropic-beta": ",".join(beta_features)} if beta_features else {}),
            },
            model.headers,
            options_headers,
        )
        client = AsyncAnthropic(
            auth_token=api_key,
            base_url=model.base_url,
            default_headers=headers,
        )
        return client

    affinity: dict[str, str] = {}
    compat = _get_anthropic_compat(model)
    if session_id and compat.send_session_affinity_headers:
        affinity["x-session-affinity"] = session_id

    headers = _merge_headers(
        {
            "accept": "application/json",
            **({"anthropic-beta": ",".join(beta_features)} if beta_features else {}),
        },
        affinity,
        model.headers,
        options_headers,
    )
    client = AsyncAnthropic(
        api_key=api_key,
        base_url=model.base_url,
        default_headers=headers,
    )
    return client


def _merge_headers(*sources: dict[str, str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for source in sources:
        if source:
            out.update(source)
    return out


def _should_use_fine_grained_tool_streaming_beta(model: Model[Any], context: Context) -> bool:
    if not context.tools:
        return False
    return not bool(_get_anthropic_compat(model).supports_eager_tool_input_streaming)


# --- Cost calculation -----------------------------------------------------


def _calculate_cost(model: Model[Any], usage: Usage) -> None:
    cost = model.cost
    usage.cost = UsageCost(
        input=usage.input * cost.input / 1_000_000,
        output=usage.output * cost.output / 1_000_000,
        cache_read=usage.cache_read * cost.cache_read / 1_000_000,
        cache_write=usage.cache_write * cost.cache_write / 1_000_000,
    )
    usage.cost.total = (
        usage.cost.input + usage.cost.output + usage.cost.cache_read + usage.cost.cache_write
    )


# --- Stop-reason mapping --------------------------------------------------


_STOP_REASON_MAP: dict[str, StopReason] = {
    "end_turn": "stop",
    "max_tokens": "length",
    "tool_use": "toolUse",
    "refusal": "error",
    "pause_turn": "stop",
    "stop_sequence": "stop",
    "sensitive": "error",
}


def _map_stop_reason(reason: str | None) -> StopReason:
    if reason is None:
        return "stop"
    mapped = _STOP_REASON_MAP.get(reason)
    if mapped is None:
        # Unknown values from the API surface as errors so the caller can decide.
        raise RuntimeError(f"Unhandled stop reason: {reason}")
    return mapped


# --- Block-tracking scratch -----------------------------------------------


@dataclass(slots=True)
class _PartialBlock:
    """Per-index block scratch state for the streaming loop."""

    kind: Literal["text", "thinking", "toolCall"]
    content_index: int  # index in `output.content`
    api_index: int  # SSE event index (anthropic.content_block_*.index)
    partial_json: str = ""


@dataclass(slots=True)
class _StreamState:
    output: AssistantMessage
    blocks_by_api_index: dict[int, _PartialBlock] = field(default_factory=dict)


# --- The two streaming entry points ---------------------------------------


def stream_anthropic(
    model: Model[Any],
    context: Context,
    options: AnthropicOptions | None = None,
) -> AssistantMessageEventStream:
    """Anthropic-messages streaming entry point.

    Failures are encoded in the returned stream (``stop_reason == "error"`` /
    ``"aborted"``) — they are never raised.
    """

    stream = AssistantMessageEventStream()

    async def runner() -> None:
        output = AssistantMessage(
            content=[],
            api=model.api,
            provider=model.provider,
            model=model.id,
            usage=Usage(),
            stop_reason="stop",
            timestamp=int(time.time() * 1000),
        )
        state = _StreamState(output=output)

        try:
            client: AsyncAnthropic

            if options and options.client is not None:
                client = options.client
            else:
                api_key = (options.api_key if options else None) or get_env_api_key(model.provider) or ""
                client = create_client(
                    model,
                    api_key,
                    interleaved_thinking=(options.interleaved_thinking if options and options.interleaved_thinking is not None else True),
                    use_fine_grained_tool_streaming_beta=_should_use_fine_grained_tool_streaming_beta(model, context),
                    options_headers=options.headers if options else None,
                    session_id=(options.session_id if options and options.cache_retention != "none" else None),
                )

            params = build_params(model, context, options)

            if options and options.on_payload is not None:
                maybe = options.on_payload(params, model)
                if asyncio.iscoroutine(maybe):
                    maybe = await maybe
                if maybe is not None and isinstance(maybe, dict):
                    params = maybe

            request_options: dict[str, Any] = {}
            if options and options.timeout_ms is not None:
                request_options["timeout"] = options.timeout_ms / 1000
            if options and options.max_retries is not None:
                request_options["max_retries"] = options.max_retries

            stream.push(StartEvent(partial=output))

            # The Python SDK exposes a streaming context manager when
            # ``stream=True``; iterate raw SSE-style events for parity with
            # pi-mono. We use ``messages.create(...).aiter_lines`` via the
            # async client's ``stream()`` helper.
            #
            # NOTE: ``params`` already has ``stream=True``; the SDK requires
            # us not to double-set, so drop it from the kwargs we pass.
            request_body = dict(params)
            request_body.pop("stream", None)
            # The SDK's overload-based typing doesn't recognize generic
            # kwarg unpacking; runtime behavior matches the pi-mono shape.
            ctx = client.messages.stream(**request_body, **request_options)

            async with ctx as message_stream:
                async for event in message_stream:
                    if options and options.signal is not None and options.signal.is_set():
                        raise asyncio.CancelledError("Request was aborted")
                    _handle_event(event, state, stream, model)

            if options and options.signal is not None and options.signal.is_set():
                raise asyncio.CancelledError("Request was aborted")
            if output.stop_reason in ("aborted", "error"):
                raise RuntimeError("An unknown error occurred")

            stream.push(DoneEvent(reason=_done_reason(output.stop_reason), message=output))
            stream.end()
        except asyncio.CancelledError as exc:
            for block in output.content:
                _strip_scratch(block)
            output.stop_reason = "aborted"
            output.error_message = "Request was aborted" if not str(exc) else str(exc)
            stream.push(ErrorEvent(reason="aborted", error=output))
            stream.end()
        except (AnthropicError, Exception) as exc:
            for block in output.content:
                _strip_scratch(block)
            aborted = bool(options and options.signal is not None and options.signal.is_set())
            output.stop_reason = "aborted" if aborted else "error"
            output.error_message = str(exc) if str(exc) else type(exc).__name__
            stream.push(ErrorEvent(reason=("aborted" if aborted else "error"), error=output))
            stream.end()

    # Keep a strong reference to the task on the stream so it isn't GC'd
    # before completion. Pi-mono's IIFE relies on JS's micro-task queue
    # holding the reference; Python's task GC needs an anchor.
    runner_task = asyncio.create_task(runner())
    stream._anthropic_runner_task = runner_task  # type: ignore[attr-defined]
    return stream


def stream_simple_anthropic(
    model: Model[Any],
    context: Context,
    options: SimpleStreamOptions | None = None,
) -> AssistantMessageEventStream:
    """``stream_simple`` entry point — maps ``reasoning`` to provider knobs."""

    if options is None:
        options = SimpleStreamOptions()
    api_key = options.api_key or get_env_api_key(model.provider)
    if not api_key:
        raise RuntimeError(f"No API key for provider: {model.provider}")

    base = build_base_options(model, options, api_key)

    if not options.reasoning:
        return stream_anthropic(
            model,
            context,
            _to_anthropic_options(base, thinking_enabled=False),
        )

    if _supports_adaptive_thinking(model.id):
        effort = _map_thinking_level_to_effort(model, options.reasoning)
        return stream_anthropic(
            model,
            context,
            _to_anthropic_options(base, thinking_enabled=True, effort=effort),
        )

    level = clamp_reasoning(options.reasoning)
    if level is None or level == "xhigh":
        level = "high"
    max_tokens, thinking_budget = adjust_max_tokens_for_thinking(
        base.max_tokens or 0,
        model.max_tokens,
        level,
        options.thinking_budgets,
    )
    return stream_anthropic(
        model,
        context,
        _to_anthropic_options(
            replace(base, max_tokens=max_tokens),
            thinking_enabled=True,
            thinking_budget_tokens=thinking_budget,
        ),
    )


# --- Helpers --------------------------------------------------------------


def _done_reason(stop_reason: StopReason) -> Literal["stop", "length", "toolUse"]:
    if stop_reason == "stop":
        return "stop"
    if stop_reason == "length":
        return "length"
    if stop_reason == "toolUse":
        return "toolUse"
    return "stop"


def _to_anthropic_options(
    base: StreamOptions,
    *,
    thinking_enabled: bool | None = None,
    effort: AnthropicEffort | None = None,
    thinking_budget_tokens: int | None = None,
) -> AnthropicOptions:
    return AnthropicOptions(
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
        thinking_enabled=thinking_enabled,
        thinking_budget_tokens=thinking_budget_tokens,
        effort=effort,
    )


def _strip_scratch(block: AssistantContent) -> None:
    """Pi-mono strips its ``partialJson`` and ``index`` scratch fields before
    persisting; our scratch is held in a separate dict keyed by API index so
    nothing to strip on the block itself."""


def _handle_event(
    event: Any,
    state: _StreamState,
    stream: AssistantMessageEventStream,
    model: Model[Any],
) -> None:
    """Dispatch one SDK event into the AssistantMessageEvent stream."""

    et = getattr(event, "type", None)
    output = state.output

    if et == "message_start":
        message = getattr(event, "message", None)
        if message is None:
            return
        output.response_id = getattr(message, "id", None)
        usage = getattr(message, "usage", None)
        if usage is not None:
            output.usage.input = getattr(usage, "input_tokens", 0) or 0
            output.usage.output = getattr(usage, "output_tokens", 0) or 0
            output.usage.cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
            output.usage.cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
            output.usage.total_tokens = (
                output.usage.input
                + output.usage.output
                + output.usage.cache_read
                + output.usage.cache_write
            )
            _calculate_cost(model, output.usage)
        return

    if et == "content_block_start":
        api_index = getattr(event, "index", -1)
        block_payload = getattr(event, "content_block", None)
        if block_payload is None:
            return
        block_type = getattr(block_payload, "type", None)
        content_index = len(output.content)

        if block_type == "text":
            output.content.append(TextContent(text=""))
            state.blocks_by_api_index[api_index] = _PartialBlock(
                kind="text", content_index=content_index, api_index=api_index
            )
            stream.push(TextStartEvent(content_index=content_index, partial=output))
            return

        if block_type == "thinking":
            output.content.append(ThinkingContent(thinking="", thinking_signature=""))
            state.blocks_by_api_index[api_index] = _PartialBlock(
                kind="thinking", content_index=content_index, api_index=api_index
            )
            stream.push(ThinkingStartEvent(content_index=content_index, partial=output))
            return

        if block_type == "redacted_thinking":
            sig = getattr(block_payload, "data", "") or ""
            output.content.append(
                ThinkingContent(thinking="[Reasoning redacted]", thinking_signature=sig, redacted=True)
            )
            state.blocks_by_api_index[api_index] = _PartialBlock(
                kind="thinking", content_index=content_index, api_index=api_index
            )
            stream.push(ThinkingStartEvent(content_index=content_index, partial=output))
            return

        if block_type == "tool_use":
            name = getattr(block_payload, "name", "")
            tool_id = getattr(block_payload, "id", "")
            initial_input = getattr(block_payload, "input", None) or {}
            output.content.append(
                ToolCall(
                    id=tool_id,
                    name=name,
                    arguments=initial_input if isinstance(initial_input, dict) else {},
                )
            )
            state.blocks_by_api_index[api_index] = _PartialBlock(
                kind="toolCall", content_index=content_index, api_index=api_index
            )
            stream.push(ToolCallStartEvent(content_index=content_index, partial=output))
            return

        return

    if et == "content_block_delta":
        api_index = getattr(event, "index", -1)
        partial = state.blocks_by_api_index.get(api_index)
        if partial is None:
            return
        delta = getattr(event, "delta", None)
        delta_type = getattr(delta, "type", None) if delta is not None else None
        block = output.content[partial.content_index]

        if delta_type == "text_delta" and isinstance(block, TextContent):
            text = getattr(delta, "text", "") or ""
            block.text += text
            stream.push(
                TextDeltaEvent(content_index=partial.content_index, delta=text, partial=output)
            )
            return

        if delta_type == "thinking_delta" and isinstance(block, ThinkingContent):
            thinking = getattr(delta, "thinking", "") or ""
            block.thinking += thinking
            stream.push(
                ThinkingDeltaEvent(content_index=partial.content_index, delta=thinking, partial=output)
            )
            return

        if delta_type == "input_json_delta" and isinstance(block, ToolCall):
            partial_json = getattr(delta, "partial_json", "") or ""
            partial.partial_json += partial_json
            block.arguments = parse_streaming_json(partial.partial_json)
            stream.push(
                ToolCallDeltaEvent(content_index=partial.content_index, delta=partial_json, partial=output)
            )
            return

        if delta_type == "signature_delta" and isinstance(block, ThinkingContent):
            signature = getattr(delta, "signature", "") or ""
            block.thinking_signature = (block.thinking_signature or "") + signature
            return

        return

    if et == "content_block_stop":
        api_index = getattr(event, "index", -1)
        partial = state.blocks_by_api_index.pop(api_index, None)
        if partial is None:
            return
        block = output.content[partial.content_index]

        if isinstance(block, TextContent):
            stream.push(
                TextEndEvent(
                    content_index=partial.content_index, content=block.text, partial=output
                )
            )
            return
        if isinstance(block, ThinkingContent):
            stream.push(
                ThinkingEndEvent(
                    content_index=partial.content_index, content=block.thinking, partial=output
                )
            )
            return
        if isinstance(block, ToolCall):
            block.arguments = parse_streaming_json(partial.partial_json)
            stream.push(
                ToolCallEndEvent(
                    content_index=partial.content_index, tool_call=block, partial=output
                )
            )
            return
        return

    if et == "message_delta":
        delta = getattr(event, "delta", None)
        stop_reason = getattr(delta, "stop_reason", None) if delta else None
        if stop_reason:
            try:
                output.stop_reason = _map_stop_reason(stop_reason)
            except RuntimeError:
                output.stop_reason = "error"
        usage = getattr(event, "usage", None)
        if usage is not None:
            input_tokens = getattr(usage, "input_tokens", None)
            output_tokens = getattr(usage, "output_tokens", None)
            cache_read = getattr(usage, "cache_read_input_tokens", None)
            cache_write = getattr(usage, "cache_creation_input_tokens", None)
            if input_tokens is not None:
                output.usage.input = input_tokens
            if output_tokens is not None:
                output.usage.output = output_tokens
            if cache_read is not None:
                output.usage.cache_read = cache_read
            if cache_write is not None:
                output.usage.cache_write = cache_write
            output.usage.total_tokens = (
                output.usage.input
                + output.usage.output
                + output.usage.cache_read
                + output.usage.cache_write
            )
            _calculate_cost(model, output.usage)
        return

    # message_stop / unknown — nothing to do.


# --- Registration ---------------------------------------------------------


class _AnthropicProvider:
    api: str = "anthropic-messages"

    def stream(
        self,
        model: Model[Any],
        context: Context,
        options: StreamOptions | None = None,
    ) -> AssistantMessageEventStream:
        anthropic_options = options if isinstance(options, AnthropicOptions) else _coerce_to_anthropic_options(options)
        return stream_anthropic(model, context, anthropic_options)

    def stream_simple(
        self,
        model: Model[Any],
        context: Context,
        options: SimpleStreamOptions | None = None,
    ) -> AssistantMessageEventStream:
        return stream_simple_anthropic(model, context, options)


def _coerce_to_anthropic_options(options: StreamOptions | None) -> AnthropicOptions | None:
    if options is None:
        return None
    if isinstance(options, AnthropicOptions):
        return options
    return AnthropicOptions(
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
    )


anthropic_provider = _AnthropicProvider()

# Pi-mono parity: register at module import.
register_api_provider(anthropic_provider)
