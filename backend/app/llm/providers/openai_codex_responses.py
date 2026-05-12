"""ChatGPT Codex Responses provider.

Codex models use the ChatGPT backend Codex Responses API with OpenAI Codex
OAuth credentials, not the Anthropic Messages API.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import replace
from typing import Any

import httpx

from app.adapters.codex_auth import (
    CodexCredentials,
    extract_account_id,
    parse_stored_oauth_token,
    refresh_access_token,
    serialize_stored_oauth_token,
)
from app.db import async_session
from app.services.credential_manager import get_credential_manager
from app.services.credential_upsert import upsert_credential

from ..api_registry import register_api_provider
from ..event_stream import AssistantMessageEventStream
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

_CODEX_API_URL = "https://chatgpt.com/backend-api/codex/responses"
_DEFAULT_INSTRUCTIONS = "You are a concise assistant."
_background_tasks: set[asyncio.Task[None]] = set()


class _CodexCredentialStore:
    def __init__(self) -> None:
        self._refresh_lock = asyncio.Lock()

    def get(self) -> CodexCredentials:
        manager = get_credential_manager()
        token_value = manager.get("codex", "oauth_token") or manager.get_api_key("codex")
        refresh_token = manager.get("codex", "refresh_token")
        access_token, expires_at = parse_stored_oauth_token(token_value)
        if not access_token:
            raise RuntimeError("No Codex OAuth token configured")
        return CodexCredentials(
            access_token=access_token,
            refresh_token=refresh_token,
            account_id=extract_account_id(access_token),
            expires_at=expires_at,
        )

    async def ensure_fresh(self) -> CodexCredentials:
        credentials = self.get()
        if not credentials.is_expired:
            return credentials
        if not credentials.refresh_token:
            raise RuntimeError("Codex OAuth token is expired and has no refresh token")

        async with self._refresh_lock:
            credentials = self.get()
            if not credentials.is_expired:
                return credentials
            if not credentials.refresh_token:
                raise RuntimeError("Codex OAuth token is expired and has no refresh token")
            refreshed = await refresh_access_token(credentials.refresh_token)
            token_value = serialize_stored_oauth_token(refreshed)
            manager = get_credential_manager()
            manager.set("codex", "oauth_token", token_value)
            if refreshed.refresh_token:
                manager.set("codex", "refresh_token", refreshed.refresh_token)
            async with async_session() as db:
                await upsert_credential(db, "codex", "oauth_token", token_value)
                if refreshed.refresh_token:
                    await upsert_credential(db, "codex", "refresh_token", refreshed.refresh_token)
            return refreshed


_credential_store = _CodexCredentialStore()


def _headers(credentials: CodexCredentials) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {credentials.access_token}",
        "chatgpt-account-id": credentials.account_id,
        "Content-Type": "application/json",
        "OpenAI-Beta": "responses=experimental",
        "Accept": "text/event-stream",
        "originator": "agent-hub",
    }


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


def _assistant_message_items(message: AssistantMessage) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    text = "".join(block.text for block in message.content if isinstance(block, TextContent))
    if text:
        items.append(
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
                "status": "completed",
                "id": message.response_id or f"msg_{message.timestamp}",
            }
        )
    for block in message.content:
        if isinstance(block, ToolCall):
            items.append(
                {
                    "type": "function_call",
                    "id": f"fc_{block.id}".replace("-", "_"),
                    "call_id": block.id,
                    "name": block.name,
                    "arguments": json.dumps(block.arguments),
                }
            )
    return items


def _input_from_context(context: Context) -> tuple[list[dict[str, Any]], str]:
    items: list[dict[str, Any]] = []
    instructions = context.system_prompt or _DEFAULT_INSTRUCTIONS
    for message in context.messages:
        if isinstance(message, ToolResultMessage):
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": message.tool_call_id,
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


def _body(
    model: Model[Any],
    context: Context,
    options: SimpleStreamOptions | None,
) -> dict[str, Any]:
    input_items, instructions = _input_from_context(context)
    body: dict[str, Any] = {
        "model": model.id,
        "instructions": instructions,
        "input": input_items,
        "stream": True,
        "store": False,
    }
    tools = _tools(context.tools)
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
        body["parallel_tool_calls"] = True
    if options and options.reasoning:
        effort = "high" if options.reasoning == "xhigh" else options.reasoning
        body["reasoning"] = {"effort": effort, "summary": "auto"}
    return body


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _usage(event: dict[str, Any], model: Model[Any]) -> Usage:
    response = _as_dict(event.get("response"))
    raw = _as_dict(response.get("usage"))
    usage = Usage(
        input=int(raw.get("input_tokens") or 0),
        output=int(raw.get("output_tokens") or 0),
    )
    usage.total_tokens = usage.input + usage.output
    usage.cost.input = usage.input * model.cost.input / 1_000_000
    usage.cost.output = usage.output * model.cost.output / 1_000_000
    usage.cost.total = usage.cost.input + usage.cost.output
    return usage


def _event_error_message(event: dict[str, Any]) -> str | None:
    event_type = event.get("type")
    if event_type == "error":
        return str(event.get("message") or event.get("code") or event)
    if event_type == "response.failed":
        response = _as_dict(event.get("response"))
        error = _as_dict(response.get("error"))
        return str(error.get("message") or "Codex response failed")
    return None


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


async def _run(
    stream: AssistantMessageEventStream,
    model: Model[Any],
    context: Context,
    options: SimpleStreamOptions | None,
) -> None:
    started_text = False
    text_parts: list[str] = []
    thinking_by_id: dict[str, list[str]] = {}
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

    try:
        credentials = await _credential_store.ensure_fresh()
        body = _body(model, context, options)
        async with (
            httpx.AsyncClient(timeout=None) as client,
            client.stream(
                "POST",
                model.base_url or _CODEX_API_URL,
                json=body,
                headers=_headers(credentials),
            ) as response,
        ):
                if response.status_code >= 400:
                    error_body = (await response.aread()).decode("utf-8", errors="replace")
                    raise RuntimeError(f"Codex HTTP {response.status_code}: {error_body}")
                async for event in _parse_sse_lines(response):
                    error_message = _event_error_message(event)
                    if error_message:
                        raise RuntimeError(error_message)

                    event_type = event.get("type", "")
                    if event_type == "response.output_text.delta":
                        delta = str(event.get("delta") or "")
                        if delta and not started_text:
                            output.content.append(TextContent(text=""))
                            stream.push(TextStartEvent(content_index=0, partial=output))
                            started_text = True
                        if delta:
                            text_parts.append(delta)
                            text_block = output.content[0]
                            if isinstance(text_block, TextContent):
                                text_block.text += delta
                            stream.push(TextDeltaEvent(content_index=0, delta=delta, partial=output))
                    elif event_type == "response.output_item.added":
                        item = _as_dict(event.get("item"))
                        item_type = item.get("type")
                        if item_type == "reasoning":
                            thinking_by_id[str(item.get("id", ""))] = []
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
                            tool_args_by_call_id[targets[0]] += str(event.get("delta") or "")
                    elif event_type == "response.output_item.done":
                        item = _as_dict(event.get("item"))
                        if item.get("type") == "function_call":
                            call_id = str(item.get("call_id") or "")
                            raw_args = tool_args_by_call_id.get(call_id) or str(item.get("arguments") or "{}")
                            try:
                                args = json.loads(raw_args) if raw_args else {}
                            except json.JSONDecodeError:
                                args = {}
                            tool_call = ToolCall(
                                id=call_id,
                                name=str(item.get("name") or ""),
                                arguments=args if isinstance(args, dict) else {},
                            )
                            tool_calls.append(tool_call)
                            index = len(output.content)
                            output.content.append(tool_call)
                            stream.push(ToolCallStartEvent(content_index=index, partial=output))
                            stream.push(ToolCallEndEvent(content_index=index, tool_call=tool_call, partial=output))
                    elif event_type in {"response.completed", "response.done"}:
                        output.usage = _usage(event, model)
                        response_payload = _as_dict(event.get("response"))
                        if isinstance(response_payload.get("id"), str):
                            output.response_id = response_payload["id"]
                        if started_text:
                            stream.push(
                                TextEndEvent(
                                    content_index=0,
                                    content="".join(text_parts),
                                    partial=output,
                                )
                            )
                        for chunks in thinking_by_id.values():
                            thinking = "".join(chunks).strip()
                            if thinking:
                                output.content.insert(0, ThinkingContent(thinking=thinking))
                        output.stop_reason = "toolUse" if tool_calls else "stop"
                        stream.push(DoneEvent(reason="toolUse" if tool_calls else "stop", message=output))
                        return
        stream.push(DoneEvent(reason="stop", message=output))
    except Exception as exc:
        error = replace(output, stop_reason="error", error_message=str(exc))
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
