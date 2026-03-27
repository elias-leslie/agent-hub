"""Streaming logic for Claude adapter."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import cast

from app.adapters.base import Message, StreamEvent
from app.adapters.claude_tools_helpers import (
    _build_mcp_server,
    _ClaudeSDKQuerySession,
    _wrap_prompt_as_stream,
)
from app.adapters.claude_utils import (
    _sdk_semaphore,
    build_sdk_options,
    extract_block_content,
    extract_system_and_conversation,
)

logger = logging.getLogger(__name__)


def _make_fallback_done(total_content: str) -> StreamEvent:
    """Build a fallback done event when the SDK did not emit one."""
    return StreamEvent(
        type="done",
        input_tokens=0,
        output_tokens=len(total_content) // 4,
        finish_reason="end_turn",
    )


def _events_for_block(block: object, is_assistant: bool) -> list[StreamEvent]:
    """Convert a single content block into zero or more StreamEvents."""
    extracted = extract_block_content(block)
    block_type = extracted["type"]

    if block_type == "text" and is_assistant:
        return [StreamEvent(type="content", content=extracted["text"])]
    if block_type == "tool_use":
        raw_input = extracted["input"]
        return [StreamEvent(
            type="tool_use",
            tool_id=extracted["id"],
            tool_name=extracted["name"],
            tool_input=raw_input if isinstance(raw_input, dict) else {},
        )]
    if block_type == "tool_result":
        return [StreamEvent(
            type="tool_result",
            tool_id=extracted["tool_use_id"],
            content=extracted["content"],
        )]
    if block_type == "thinking" and is_assistant:
        return [StreamEvent(type="thinking", content=extracted["thinking"])]
    return []


def _events_for_message(message: object) -> list[StreamEvent]:
    """Convert a non-result SDK message into zero or more StreamEvents."""
    from claude_agent_sdk.types import AssistantMessage

    content_blocks = getattr(message, "content", None)
    if not isinstance(content_blocks, list):
        return []
    is_assistant = isinstance(message, AssistantMessage)
    events: list[StreamEvent] = []
    for block in content_blocks:
        events.extend(_events_for_block(block, is_assistant))
    return events


def _make_result_event(message: object) -> StreamEvent:
    """Build a done StreamEvent from a ResultMessage."""
    usage = getattr(message, "usage", None) or {}
    return StreamEvent(
        type="done",
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        finish_reason="end_turn",
    )


def _create_abort_watch_task(
    abort_event: asyncio.Event,
    session: object,
) -> "asyncio.Task[None]":
    """Create a background task that interrupts the session when abort fires."""
    async def _watch_abort() -> None:
        await abort_event.wait()
        await session.interrupt()  # type: ignore[attr-defined]

    return asyncio.create_task(_watch_abort())


async def _cancel_abort_watch(task: "asyncio.Task[None] | None") -> None:
    """Cancel and await the abort-watch task if it exists."""
    if task is not None:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


async def _iterate_sdk_messages(
    message_iter: object,
    abort_event: asyncio.Event | None,
    session: object,
) -> AsyncIterator[StreamEvent]:
    """Yield StreamEvents by iterating raw SDK messages."""
    from claude_agent_sdk.types import ResultMessage

    done_emitted = False
    while True:
        if abort_event is not None and abort_event.is_set():
            await session.interrupt()  # type: ignore[attr-defined]
            raise asyncio.CancelledError("Abort signal received")
        try:
            message = await anext(cast(AsyncIterator[object], message_iter))
        except StopAsyncIteration:
            return
        if isinstance(message, ResultMessage):
            yield _make_result_event(message)
            done_emitted = True
            return
        if done_emitted:
            continue
        for event in _events_for_message(message):
            yield event


async def _yield_sdk_events(
    prompt: object,
    options: object,
    abort_event: asyncio.Event | None = None,
) -> AsyncIterator[StreamEvent]:
    """Yield StreamEvents from SDK query; prompt may be str or async iterable."""
    session = _ClaudeSDKQuerySession(prompt=prompt, options=options)
    await session.start()
    message_iter = session.message_iter
    if message_iter is None:
        raise RuntimeError("Claude SDK query session did not initialize an iterator")

    abort_watch_task = (
        _create_abort_watch_task(abort_event, session)
        if abort_event is not None
        else None
    )
    try:
        async for event in _iterate_sdk_messages(message_iter, abort_event, session):
            yield event
    finally:
        await _cancel_abort_watch(abort_watch_task)
        await session.close()


def _build_oauth_options(
    tools: object, working_dir: object, project_id: object,
    cli_path: str, model: str, model_map: dict[str, str], system_prompt: str | None,
) -> tuple[object, bool]:
    """Build SDK options and streaming-prompt flag for OAuth streaming."""
    mcp_server = (
        _build_mcp_server(
            tools=tools,
            working_dir=working_dir,
            project_id=project_id,
            agent_slug=None,
            tool_catalog=None,
        )
        if tools
        else None
    )
    # Build allowed_tools including MCP tool names
    from app.adapters._claude_constants import build_allowed_tools

    allowed_tools = build_allowed_tools(tools) if tools else None
    return build_sdk_options(
        cli_path=cli_path, model=model, model_map=model_map,
        working_dir=working_dir, system_prompt=system_prompt,
        mcp_servers={"agent-hub": mcp_server} if mcp_server else None,
        allowed_tools=allowed_tools,
    )


async def _gated_sdk_events(
    prompt: object,
    options: object,
    abort_event: asyncio.Event | None = None,
) -> AsyncIterator[StreamEvent]:
    """Yield SDK events under the global concurrency semaphore."""
    async with _sdk_semaphore:
        async for event in _yield_sdk_events(prompt, options, abort_event=abort_event):
            yield event


def _make_cancelled_done(total_content: str) -> StreamEvent:
    """Build a done event with cancelled finish reason."""
    return StreamEvent(
        type="done",
        input_tokens=0,
        output_tokens=len(total_content) // 4,
        finish_reason="cancelled",
    )


async def stream_oauth(
    messages: list[Message],
    model: str,
    cli_path: str,
    model_map: dict[str, str],
    **kwargs: object,
) -> AsyncIterator[StreamEvent]:
    """Stream using OAuth via Claude Agent SDK with optional MCP tool integration."""
    kwargs.pop("cache_retention", None)
    tools = kwargs.pop("tools", None)
    working_dir = kwargs.get("working_dir", ".")
    project_id = kwargs.get("project_id")
    abort_event = kwargs.get("abort_event")
    system_prompt, conversation_prompt = extract_system_and_conversation(messages)
    options, use_streaming_prompt = _build_oauth_options(
        tools, working_dir, project_id, cli_path, model, model_map, system_prompt)
    prompt: object = (
        await _wrap_prompt_as_stream(conversation_prompt) if use_streaming_prompt
        else conversation_prompt
    )
    safe_abort = abort_event if isinstance(abort_event, asyncio.Event) else None
    total_content = ""
    got_done = False
    try:
        async for event in _gated_sdk_events(prompt, options, abort_event=safe_abort):
            if event.type == "content":
                total_content += event.content or ""
            if event.type == "done":
                got_done = True
            yield event
        if not got_done:
            yield _make_fallback_done(total_content)
    except asyncio.CancelledError:
        logger.warning("Claude SDK stream cancelled (cancel scope); emitting cancelled done")
        if not got_done:
            yield _make_cancelled_done(total_content)
    except TimeoutError:
        logger.error("Claude OAuth stream timeout")
        yield StreamEvent(type="error", error="Claude OAuth stream timeout")
        if not got_done:
            yield _make_fallback_done(total_content)
    except Exception as e:
        logger.error("Claude SDK stream error: %s", e)
        yield StreamEvent(type="error", error=str(e))
        if not got_done:
            yield _make_fallback_done(total_content)
