"""Streaming logic for Claude adapter."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import suppress

from app.adapters.base import Message, StreamEvent
from app.adapters.claude_tools_helpers import _build_mcp_server, _wrap_prompt_as_stream
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


async def _yield_sdk_events(prompt: object, options: object) -> AsyncIterator[StreamEvent]:
    """Yield StreamEvents from SDK query; prompt may be str or async iterable."""
    from claude_agent_sdk import query
    from claude_agent_sdk.types import AssistantMessage, ResultMessage

    done_emitted = False
    message_iter = query(prompt=prompt, options=options).__aiter__()
    try:
        while True:
            try:
                message = await anext(message_iter)
            except StopAsyncIteration:
                return
            if isinstance(message, ResultMessage):
                usage = message.usage or {}
                yield StreamEvent(
                    type="done",
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0),
                    finish_reason="end_turn",
                )
                done_emitted = True
                return
            if done_emitted:
                continue
            # Include all message types: ToolResultBlock arrives in non-assistant messages.
            content_blocks = getattr(message, "content", None)
            if not isinstance(content_blocks, list):
                continue

            is_assistant = isinstance(message, AssistantMessage)
            for block in content_blocks:
                for event in _events_for_block(block, is_assistant):
                    yield event
    finally:
        if hasattr(message_iter, "aclose"):
            with suppress(Exception):
                await message_iter.aclose()


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


async def _gated_sdk_events(prompt: object, options: object) -> AsyncIterator[StreamEvent]:
    """Yield SDK events under the global concurrency semaphore."""
    async with _sdk_semaphore:
        async for event in _yield_sdk_events(prompt, options):
            yield event


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
    system_prompt, conversation_prompt = extract_system_and_conversation(messages)
    options, use_streaming_prompt = _build_oauth_options(
        tools, working_dir, project_id, cli_path, model, model_map, system_prompt)
    prompt: object = (
        await _wrap_prompt_as_stream(conversation_prompt) if use_streaming_prompt
        else conversation_prompt
    )
    total_content = ""
    got_done = False
    try:
        async for event in _gated_sdk_events(prompt, options):
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
            yield StreamEvent(
                type="done",
                input_tokens=0,
                output_tokens=len(total_content) // 4,
                finish_reason="cancelled",
            )
    except TimeoutError:
        logger.error("Claude OAuth stream timeout: request exceeded 300s")
        yield StreamEvent(type="error", error="Request timeout exceeded 300s")
        if not got_done:
            yield _make_fallback_done(total_content)
    except Exception as e:
        logger.error("Claude SDK stream error: %s", e)
        yield StreamEvent(type="error", error=str(e))
        if not got_done:
            yield _make_fallback_done(total_content)
