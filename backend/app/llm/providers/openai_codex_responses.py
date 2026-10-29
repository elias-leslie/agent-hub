"""ChatGPT Codex Responses provider.

Codex models use the ChatGPT backend Codex Responses API with OpenAI Codex
OAuth credentials, not the Anthropic Messages API.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import Any

import httpx

from app.adapters.codex_auth import (
    CodexCredentials,
)
from app.config import settings
from app.services.codex_credentials import (
    cached_codex_credentials,
    ensure_fresh_codex_credentials,
)
from app.services.llm_errors import (
    AuthenticationError,
    ProviderError,
    RateLimitError,
    extract_openai_rate_limit_header,
    extract_retry_after_header,
)

from ..api_registry import register_api_provider
from ..event_stream import AssistantMessageEventStream
from ..transform_messages import transform_messages
from ..types import (
    AssistantMessage,
    Context,
    DoneEvent,
    ErrorEvent,
    ImageContent,
    Model,
    SimpleStreamOptions,
    StartEvent,
    TextContent,
    TextDeltaEvent,
    TextEndEvent,
    TextStartEvent,
    ThinkingContent,
    Tool,
    ToolCall,
    ToolCallEndEvent,
    ToolCallStartEvent,
    ToolResultMessage,
    Usage,
)
from ..utils.abort import cancel_on_signal
from ..utils.outcomes import ProviderOutcome, is_model_switch, record_outcome
from ..utils.refusal_codes import codex_refusal_category
from ..utils.request_metrics import record_request_metrics
from ..utils.stream_timeout import note_timeout, stream_timeout

logger = logging.getLogger(__name__)

_CODEX_API_URL = "https://chatgpt.com/backend-api/codex/responses"
_DEFAULT_INSTRUCTIONS = "You are a concise assistant."
_background_tasks: set[asyncio.Task[None]] = set()
_ID_PART_RE = re.compile(r"[^a-zA-Z0-9_-]")
# OpenAI rejects prompt_cache_key values longer than this.
_PROMPT_CACHE_KEY_MAX_LENGTH = 64


class _CodexCredentialStore:
    def get(self) -> CodexCredentials:
        return cached_codex_credentials()

    async def ensure_fresh(self) -> CodexCredentials:
        return await ensure_fresh_codex_credentials()

    async def recover_after_auth_failure(
        self,
        stale_access_token: str,
        expected_account_id: str,
    ) -> CodexCredentials:
        return await ensure_fresh_codex_credentials(
            force_refresh=True,
            stale_access_token=stale_access_token,
            expected_account_id=expected_account_id,
        )


_credential_store = _CodexCredentialStore()


def _headers(credentials: CodexCredentials, cache_key: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {credentials.access_token}",
        "chatgpt-account-id": credentials.account_id,
        "Content-Type": "application/json",
        "OpenAI-Beta": "responses=experimental",
        "Accept": "text/event-stream",
        "originator": "agent-hub",
    }
    if cache_key:
        # Session affinity keeps a conversation on the backend that holds its prompt cache.
        headers["session-id"] = cache_key
        headers["x-client-request-id"] = cache_key
    return headers


def _cache_key(options: SimpleStreamOptions | None) -> str | None:
    if options is None or options.cache_retention == "none" or not options.session_id:
        return None
    return options.session_id[:_PROMPT_CACHE_KEY_MAX_LENGTH]


def _text_from_user_content(content: str | list[TextContent | ImageContent]) -> str:
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, TextContent):
            parts.append(block.text)
    return "\n".join(part for part in parts if part)


def _tool_result_text(message: ToolResultMessage) -> str:
    parts: list[str] = []
    for block in message.content:
        if isinstance(block, TextContent):
            parts.append(block.text)
    return "\n".join(part for part in parts if part)


def _sanitize_id_part(value: str) -> str:
    sanitized = _ID_PART_RE.sub("_", value).strip("_")
    return sanitized[:64].rstrip("_")


def _parse_text_signature(signature: str | None) -> tuple[str | None, str | None]:
    if not signature:
        return None, None
    msg_id = signature
    phase = None
    if signature.startswith("{"):
        try:
            payload = json.loads(signature)
        except json.JSONDecodeError:
            return None, None
        if not isinstance(payload, dict):
            return None, None
        msg_id = payload.get("id")
        raw_phase = payload.get("phase")
        phase = raw_phase if raw_phase in {"commentary", "final_answer"} else None
    if not isinstance(msg_id, str) or not msg_id.startswith("msg_") or len(msg_id) > 64:
        return None, phase
    return msg_id, phase


def _encode_text_signature(msg_id: str, phase: str | None = None) -> str:
    payload: dict[str, Any] = {"v": 1, "id": msg_id}
    if phase in {"commentary", "final_answer"}:
        payload["phase"] = phase
    return json.dumps(payload, separators=(",", ":"))


def _assistant_message_id(message: AssistantMessage) -> tuple[str, str | None]:
    for block in message.content:
        if isinstance(block, TextContent):
            msg_id, phase = _parse_text_signature(block.text_signature)
            if msg_id:
                return msg_id, phase
    return f"msg_{message.timestamp}", None


def _split_responses_tool_call_id(tool_call_id: str) -> tuple[str, str | None]:
    call_id, sep, item_id = tool_call_id.partition("|")
    return call_id, item_id if sep else None


def _responses_tool_item_id(tool_call_id: str) -> str:
    call_id, item_id = _split_responses_tool_call_id(tool_call_id)
    if item_id and item_id.startswith("fc_") and len(item_id) <= 64:
        return item_id
    normalized = _sanitize_id_part(call_id)
    if not normalized.startswith("fc_"):
        normalized = f"fc_{normalized}"
    return normalized[:64].rstrip("_")


def _reasoning_item(block: ThinkingContent) -> dict[str, Any] | None:
    # Same-model reasoning keeps the full Responses item, encrypted content included.
    if not block.thinking_signature or not block.thinking_signature.startswith("{"):
        return None
    try:
        item = json.loads(block.thinking_signature)
    except json.JSONDecodeError:
        return None
    return item if isinstance(item, dict) and item.get("type") == "reasoning" else None


def _assistant_message_items(message: AssistantMessage) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = [
        item
        for block in message.content
        if isinstance(block, ThinkingContent) and (item := _reasoning_item(block)) is not None
    ]
    text = "".join(block.text for block in message.content if isinstance(block, TextContent))
    if text:
        msg_id, phase = _assistant_message_id(message)
        item: dict[str, Any] = {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": text, "annotations": []}],
            "status": "completed",
            "id": msg_id,
        }
        if phase:
            item["phase"] = phase
        items.append(item)
    for block in message.content:
        if isinstance(block, ToolCall):
            call_id, _item_id = _split_responses_tool_call_id(block.id)
            items.append(
                {
                    "type": "function_call",
                    "id": _responses_tool_item_id(block.id),
                    "call_id": call_id,
                    "name": block.name,
                    "arguments": json.dumps(block.arguments),
                }
            )
    return items


def _input_from_context(
    context: Context, model: Model[Any] | None = None
) -> tuple[list[dict[str, Any]], str]:
    items: list[dict[str, Any]] = []
    instructions = context.system_prompt or _DEFAULT_INSTRUCTIONS
    # Drops other models' reasoning and failed turns, and closes orphaned tool calls.
    messages = transform_messages(context.messages, model) if model is not None else context.messages
    for message in messages:
        if isinstance(message, ToolResultMessage):
            call_id, _item_id = _split_responses_tool_call_id(message.tool_call_id)
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": _tool_result_text(message),
                }
            )
        elif isinstance(message, AssistantMessage):
            items.extend(_assistant_message_items(message))
        else:
            items.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": _text_from_user_content(message.content),
                        }
                    ],
                }
            )
    return items, instructions


def _thinking_blocks(
    thinking_by_id: dict[str, list[str]], reasoning_items: dict[str, dict[str, Any]]
) -> list[ThinkingContent]:
    blocks: list[ThinkingContent] = []
    for item_id in dict.fromkeys([*thinking_by_id, *reasoning_items]):
        thinking = "".join(thinking_by_id.get(item_id, [])).strip()
        item = reasoning_items.get(item_id)
        signature = json.dumps(item, separators=(",", ":")) if item and item.get("encrypted_content") else None
        if thinking or signature:
            blocks.append(ThinkingContent(thinking=thinking, thinking_signature=signature))
    return blocks


def _tools(tools: list[Tool] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [
        {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        }
        for tool in tools
    ]



_KEEPALIVE = "keepalive"


def _body(
    model: Model[Any],
    context: Context,
    options: SimpleStreamOptions | None,
) -> dict[str, Any]:
    input_items, instructions = _input_from_context(context, model)
    body: dict[str, Any] = {
        "model": model.id,
        "instructions": instructions,
        "input": input_items,
        "stream": True,
        "store": False,
    }
    if cache_key := _cache_key(options):
        body["prompt_cache_key"] = cache_key
    if model.access_programs:
        # Program-gated models (Daybreak Blue) reject requests that omit their program.
        body["access_programs"] = dict(model.access_programs)
    tools = _tools(context.tools)
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
        body["parallel_tool_calls"] = True
    if options and options.reasoning:
        # The catalog's thinking_level_map declares per-model level support.
        level_map = model.thinking_level_map or {}
        effort = level_map.get(options.reasoning, options.reasoning)
        if effort is None:
            raise ValueError(f"{model.id} does not support {options.reasoning} reasoning")
        body["reasoning"] = {"effort": effort, "summary": "auto"}
        # With store=false, replaying encrypted reasoning is the only way the next call keeps it.
        body["include"] = ["reasoning.encrypted_content"]
    return body


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _usage(event: dict[str, Any], model: Model[Any]) -> Usage:
    response = _as_dict(event.get("response"))
    raw = _as_dict(response.get("usage"))
    total_input = int(raw.get("input_tokens") or 0)
    cached_input = int(_as_dict(raw.get("input_tokens_details")).get("cached_tokens") or 0)
    usage = Usage(
        input=max(0, total_input - cached_input),
        output=int(raw.get("output_tokens") or 0),
        cache_read=cached_input,
        reasoning=int(_as_dict(raw.get("output_tokens_details")).get("reasoning_tokens") or 0),
    )
    usage.total_tokens = total_input + usage.output
    usage.cost.input = usage.input * model.cost.input / 1_000_000
    usage.cost.output = usage.output * model.cost.output / 1_000_000
    usage.cost.cache_read = usage.cache_read * model.cost.cache_read / 1_000_000
    usage.cost.total = usage.cost.input + usage.cost.output + usage.cost.cache_read
    return usage


class _CodexRefusal(RuntimeError):
    """A Codex safety refusal; ``category`` is the shared refusal category."""

    def __init__(self, message: str, category: str) -> None:
        super().__init__(message)
        self.category = category


def _event_error_code(event: dict[str, Any]) -> object:
    event_type = event.get("type")
    if event_type == "error":
        return event.get("code") or _as_dict(event.get("error")).get("code")
    if event_type == "response.failed":
        return _as_dict(_as_dict(event.get("response")).get("error")).get("code")
    return None


def _event_error_message(event: dict[str, Any]) -> str | None:
    event_type = event.get("type")
    if event_type == "error":
        return str(event.get("message") or event.get("code") or event)
    if event_type == "response.failed":
        response = _as_dict(event.get("response"))
        error = _as_dict(response.get("error"))
        return str(error.get("message") or "Codex response failed")
    return None


def _raise_codex_http_error(status_code: int, body: str, headers: Any) -> None:
    """Map a Codex HTTP error response onto the shared provider-error taxonomy.

    Routing into ``RateLimitError`` / ``AuthenticationError`` / retriable
    ``ProviderError`` is what lets the upstream fallback orchestrator
    cool down and switch providers instead of burning the whole chain.
    """
    header_map: dict[str, str] = {}
    try:
        header_map = {str(k): str(v) for k, v in dict(headers).items()}
    except Exception:
        header_map = {}
    snippet = body[:500]
    if status_code == 429:
        retry_after = extract_retry_after_header(header_map, max_delay=60.0)
        if retry_after is None:
            retry_after = extract_openai_rate_limit_header(header_map, max_delay=60.0)
        raise RateLimitError("codex", retry_after=retry_after)
    if status_code in (401, 403):
        raise AuthenticationError("codex")
    if status_code >= 500:
        raise ProviderError(
            f"Codex HTTP {status_code}: {snippet}",
            provider="codex",
            retriable=True,
            status_code=status_code,
        )
    raise ProviderError(
        f"Codex HTTP {status_code}: {snippet}",
        provider="codex",
        retriable=False,
        status_code=status_code,
    )


async def _parse_sse_lines(response: httpx.Response):
    async for line in response.aiter_lines():
        if not line.startswith("data: "):
            continue
        raw = line[6:].strip()
        if raw == "[DONE]":
            return
        try:
            yield json.loads(raw)
        except json.JSONDecodeError:
            continue


@asynccontextmanager
async def _authenticated_response(
    client: httpx.AsyncClient,
    model: Model[Any],
    body: dict[str, Any],
    cache_key: str | None = None,
):
    """Open a Codex stream, recovering once from a pre-stream HTTP 401."""
    credentials = await _credential_store.ensure_fresh()
    for attempt in range(2):
        response_context = client.stream(
            "POST",
            model.base_url or _CODEX_API_URL,
            json=body,
            headers=_headers(credentials, cache_key),
        )
        response = await response_context.__aenter__()
        try:
            if response.status_code == 401 and attempt == 0:
                await response.aread()
                credentials = await _credential_store.recover_after_auth_failure(
                    credentials.access_token,
                    credentials.account_id,
                )
                continue
            yield response
            return
        finally:
            await response_context.__aexit__(None, None, None)
    raise RuntimeError("Codex authentication recovery exhausted")


class _Timing:
    """Where one request spent its time: the longest silence between frames, keepalives and tool-argument stream.

    The record rides on the message (``request_metrics``) so it is persisted with the session; at DEBUG
    (``LOG_LEVELS=app.llm=DEBUG``) it is logged too.
    """

    def __init__(self) -> None:
        self.start = self.last = self.last_event = time.monotonic()
        self.headers: float | None = None
        self.first: float | None = None
        self.max_gap = 0.0
        self.max_event_gap = 0.0
        self.events = 0
        self.keepalives = 0
        self.max_tool_args = 0
        self.failure: str | None = None

    def frame(self, keepalive: bool) -> None:
        """One SSE frame arrived. Any frame, keepalives included, proves the connection is alive."""
        now = time.monotonic()
        self.max_gap = max(self.max_gap, now - self.last)
        self.last = now
        if keepalive:
            self.keepalives += 1
            return
        if self.first is None:
            self.first = now - self.start
        self.max_event_gap = max(self.max_event_gap, now - self.last_event)
        self.last_event = now
        self.events += 1

    def metrics(self) -> dict[str, Any]:
        return {
            "headers_s": None if self.headers is None else round(self.headers, 2),
            "first_event_s": None if self.first is None else round(self.first, 2),
            "max_gap_s": round(self.max_gap, 2),
            "max_event_gap_s": round(self.max_event_gap, 2),
            "events": self.events,
            "keepalives": self.keepalives,
            "max_tool_args": self.max_tool_args,
            "total_s": round(time.monotonic() - self.start, 2),
            "outcome": self.failure or "ok",
        }

    def finish(self, model: str, message: AssistantMessage) -> None:
        metrics = self.metrics()
        record_request_metrics(message, **metrics)
        logger.debug("codex request model=%s %s", model, " ".join(f"{k}={v}" for k, v in metrics.items()))


class _Interrupted(Exception):
    """A stream that died before completing: EOF before ``response.completed``, or a failed response a re-send can fix."""


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, _Interrupted | httpx.TransportError):  # EOF, dropped or refused connection, read timeout
        return True
    # A rate limit goes to the shared cooldown and fallback instead.
    return isinstance(exc, ProviderError) and exc.retriable and not isinstance(exc, RateLimitError)


def _failed_response(event: dict[str, Any], message: str) -> Exception:
    """The exception for a ``response.failed``/``error`` event: a refusal, a fatal error, or an interruption.

    Like Codex CLI, a failed response is re-sent unless its code says a re-send cannot help.
    """
    code = _event_error_code(event)
    category = codex_refusal_category(code)
    if category:
        return _CodexRefusal(message, category)
    if str(code or "").lower() in {c.lower() for c in settings.llm_fatal_error_codes}:
        return RuntimeError(message)
    return _Interrupted(message)


async def _run(
    stream: AssistantMessageEventStream,
    model: Model[Any],
    context: Context,
    options: SimpleStreamOptions | None,
) -> None:
    """One streamed response. It never re-sends: a death is reported as an ``interrupted`` outcome and
    ``tool_loop.run_turn`` re-runs the turn, so the retry budget is spent in exactly one place."""
    started_text = False
    current_text_index: int | None = None
    current_message_item_id: str | None = None
    current_message_phase: str | None = None
    text_parts: list[str] = []
    thinking_by_id: dict[str, list[str]] = {}
    reasoning_items: dict[str, dict[str, Any]] = {}
    tool_args_by_call_id: dict[str, str] = {}
    tool_calls: list[ToolCall] = []
    output = AssistantMessage(
        content=[],
        api=model.api,
        provider=model.provider,
        model=model.id,
        usage=Usage(),
        stop_reason="stop",
        timestamp=int(time.time() * 1000),
    )
    stream.push(StartEvent(partial=output))

    timing = _Timing()
    try:
        body = _body(model, context, options)
        async with (
            httpx.AsyncClient(timeout=stream_timeout(options.timeout_ms if options else None)) as client,
            _authenticated_response(client, model, body, _cache_key(options)) as response,
        ):
                timing.headers = time.monotonic() - timing.start
                if response.status_code >= 400:
                    error_body = (await response.aread()).decode("utf-8", errors="replace")
                    _raise_codex_http_error(response.status_code, error_body, response.headers)
                async for event in _parse_sse_lines(response):
                    timing.frame(event.get("type") == _KEEPALIVE)
                    if options is not None and options.signal is not None and options.signal.is_set():
                        error = replace(output, stop_reason="aborted", error_message="Request was aborted")
                        timing.failure = "aborted"
                        timing.finish(model.id, error)
                        stream.push(ErrorEvent(reason="aborted", error=error))
                        return
                    error_message = _event_error_message(event)
                    if error_message:
                        raise _failed_response(event, error_message)

                    event_type = event.get("type", "")
                    if event_type == _KEEPALIVE:
                        continue
                    if event_type == "response.output_text.delta":
                        delta = str(event.get("delta") or "")
                        if delta and not started_text:
                            current_text_index = len(output.content)
                            output.content.append(TextContent(text=""))
                            stream.push(TextStartEvent(content_index=current_text_index, partial=output))
                            started_text = True
                        if delta:
                            text_parts.append(delta)
                            text_block = output.content[current_text_index or 0]
                            if isinstance(text_block, TextContent):
                                text_block.text += delta
                            stream.push(TextDeltaEvent(content_index=current_text_index or 0, delta=delta, partial=output))
                    elif event_type == "response.output_item.added":
                        item = _as_dict(event.get("item"))
                        item_type = item.get("type")
                        if item_type == "reasoning":
                            thinking_by_id[str(item.get("id", ""))] = []
                        elif item_type == "message":
                            item_id = str(item.get("id") or "")
                            current_message_item_id = item_id if item_id.startswith("msg_") else None
                            raw_phase = item.get("phase")
                            current_message_phase = raw_phase if raw_phase in {"commentary", "final_answer"} else None
                        elif item_type == "function_call":
                            call_id = str(item.get("call_id") or "")
                            if call_id:
                                tool_args_by_call_id[call_id] = str(item.get("arguments") or "")
                    elif event_type == "response.reasoning_summary_text.delta":
                        item_id = str(event.get("item_id") or "")
                        targets = [item_id] if item_id in thinking_by_id else list(thinking_by_id)[-1:]
                        if targets:
                            thinking_by_id[targets[0]].append(str(event.get("delta") or ""))
                    elif event_type == "response.function_call_arguments.delta":
                        call_id = str(event.get("call_id") or "")
                        targets = [call_id] if call_id in tool_args_by_call_id else list(tool_args_by_call_id)[-1:]
                        if targets:
                            call_id = targets[0]
                            tool_args_by_call_id[call_id] += str(event.get("delta") or "")
                            timing.max_tool_args = max(timing.max_tool_args, len(tool_args_by_call_id[call_id]))
                    elif event_type == "response.output_item.done":
                        item = _as_dict(event.get("item"))
                        if item.get("type") == "reasoning":
                            reasoning_items[str(item.get("id", ""))] = item
                        elif item.get("type") == "function_call":
                            call_id = str(item.get("call_id") or "")
                            raw_args = tool_args_by_call_id.get(call_id) or str(item.get("arguments") or "{}")
                            try:
                                args = json.loads(raw_args) if raw_args else {}
                            except json.JSONDecodeError:
                                args = {}
                            item_id = str(item.get("id") or "")
                            tool_call_id = f"{call_id}|{item_id}" if item_id else call_id
                            tool_call = ToolCall(
                                id=tool_call_id,
                                name=str(item.get("name") or ""),
                                arguments=args if isinstance(args, dict) else {},
                            )
                            tool_calls.append(tool_call)
                            index = len(output.content)
                            output.content.append(tool_call)
                            stream.push(ToolCallStartEvent(content_index=index, partial=output))
                            stream.push(ToolCallEndEvent(content_index=index, tool_call=tool_call, partial=output))
                        elif item.get("type") == "message" and current_text_index is not None:
                            item_id = str(item.get("id") or current_message_item_id or "")
                            text_block = output.content[current_text_index]
                            if item_id.startswith("msg_") and isinstance(text_block, TextContent):
                                text_block.text_signature = _encode_text_signature(item_id, current_message_phase)
                    elif event_type in {"response.completed", "response.done"}:
                        output.usage = _usage(event, model)
                        response_payload = _as_dict(event.get("response"))
                        reported_model = response_payload.get("model")
                        if isinstance(reported_model, str) and reported_model.strip():
                            output.response_model = reported_model.strip()
                            if is_model_switch(model.id, output.response_model):
                                record_outcome(
                                    output,
                                    ProviderOutcome(
                                        kind="substituted",
                                        requested_model=model.id,
                                        served_model=output.response_model,
                                    ),
                                )
                        if isinstance(response_payload.get("id"), str):
                            output.response_id = response_payload["id"]
                        if started_text:
                            stream.push(
                                TextEndEvent(
                                    content_index=current_text_index or 0,
                                    content="".join(text_parts),
                                    partial=output,
                                )
                            )
                        output.content[0:0] = _thinking_blocks(thinking_by_id, reasoning_items)
                        output.stop_reason = "toolUse" if tool_calls else "stop"
                        timing.finish(model.id, output)
                        stream.push(DoneEvent(reason="toolUse" if tool_calls else "stop", message=output))
                        return
        # The stream ended without response.completed: a partial message is not an answer.
        raise _Interrupted("stream ended before response.completed")
    except asyncio.CancelledError:
        # The abort signal cancelled this task (see ``cancel_on_signal``); leaving the ``async with`` closed the HTTP stream.
        error = replace(output, stop_reason="aborted", error_message="Request was aborted")
        timing.failure = "aborted"
        timing.finish(model.id, error)
        stream.push(ErrorEvent(reason="aborted", error=error))
    except Exception as exc:
        silence = note_timeout(exc, model.id, options.timeout_ms if options else None)
        timing.failure = silence or repr(exc)[:200]
        error = replace(output, stop_reason="error", error_message=silence or str(exc))
        if isinstance(exc, _CodexRefusal):
            record_outcome(
                error,
                ProviderOutcome(
                    kind="refused",
                    requested_model=model.id,
                    served_model=error.response_model,
                    category=exc.category,
                    explanation=str(exc),
                ),
            )
        elif _retryable(exc):
            record_outcome(
                error,
                ProviderOutcome(kind="interrupted", requested_model=model.id, explanation=silence or str(exc) or type(exc).__name__),
            )
        timing.finish(model.id, error)
        stream.push(ErrorEvent(reason="error", error=error))


class _OpenAICodexResponsesProvider:
    api = "openai-codex-responses"

    def stream(
        self,
        model: Model[Any],
        context: Context,
        options: SimpleStreamOptions | None = None,
    ) -> AssistantMessageEventStream:
        stream = AssistantMessageEventStream()
        task = asyncio.create_task(_run(stream, model, context, options))
        cancel_on_signal(task, options.signal if options else None)
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
        return stream

    def stream_simple(
        self,
        model: Model[Any],
        context: Context,
        options: SimpleStreamOptions | None = None,
    ) -> AssistantMessageEventStream:
        return self.stream(model, context, options)


openai_codex_responses_provider = _OpenAICodexResponsesProvider()
register_api_provider(openai_codex_responses_provider)
