"""Streaming logic for Claude adapter."""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from app.adapters.base import Message, StreamEvent
from app.adapters.claude_utils import (
    _sdk_semaphore,
    build_sdk_options,
    extract_block_content,
    extract_system_and_conversation,
)

logger = logging.getLogger(__name__)


async def _yield_sdk_events(full_prompt: str, options: Any) -> AsyncIterator[StreamEvent]:
    """Yield StreamEvents from the Claude Agent SDK query.

    Emits content, tool_use, and tool_result events so the shared streaming
    loop can track tool execution without re-executing tools the CLI already ran.
    """
    from claude_agent_sdk import query
    from claude_agent_sdk.types import AssistantMessage, ResultMessage

    async for message in query(prompt=full_prompt, options=options):
        if isinstance(message, ResultMessage):
            usage = message.usage or {}
            yield StreamEvent(
                type="done",
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                finish_reason="end_turn",
            )
            return

        # Extract content blocks from any message type (not just AssistantMessage).
        # The SDK sends ToolResultBlock in non-AssistantMessage messages (e.g. user
        # role messages after tool execution).  Skipping those caused tool results
        # to be silently dropped.
        content_blocks = getattr(message, "content", None)
        if not isinstance(content_blocks, list):
            continue

        is_assistant = isinstance(message, AssistantMessage)
        for block in content_blocks:
            extracted = extract_block_content(block)
            if extracted["type"] == "text":
                if is_assistant:
                    yield StreamEvent(type="content", content=extracted["text"])
            elif extracted["type"] == "tool_use":
                yield StreamEvent(
                    type="tool_use",
                    tool_id=extracted["id"],
                    tool_name=extracted["name"],
                    tool_input=extracted["input"] if isinstance(extracted["input"], dict) else {},
                )
            elif extracted["type"] == "tool_result":
                yield StreamEvent(
                    type="tool_result",
                    tool_id=extracted["tool_use_id"],
                    content=extracted["content"],
                )


async def stream_oauth(
    messages: list[Message],
    model: str,
    cli_path: str,
    model_map: dict[str, str],
    **kwargs: Any,
) -> AsyncIterator[StreamEvent]:
    """Stream using OAuth via Claude Agent SDK.

    Accepts ``cache_retention`` via kwargs ("none", "short", "long").
    The Claude Agent SDK abstracts the HTTP layer so cache_control headers
    cannot be injected directly.  The parameter is consumed here to prevent
    it from leaking into SDK options and will become actionable when a
    direct Anthropic API streaming adapter is added.
    """
    # cache_retention is accepted for forward-compatibility but is not yet
    # actionable through the Claude Agent SDK streaming path.
    cache_retention = kwargs.pop("cache_retention", "none")
    if cache_retention != "none":
        logger.debug(
            "cache_retention=%s requested but Claude Agent SDK streaming does "
            "not support cache_control headers; parameter ignored",
            cache_retention,
        )

    system_prompt, conversation_prompt = extract_system_and_conversation(messages)
    options, _ = build_sdk_options(
        cli_path=cli_path,
        model=model,
        model_map=model_map,
        working_dir=kwargs.get("working_dir", "."),
        system_prompt=system_prompt,
    )

    total_content = ""
    got_done = False
    async with _sdk_semaphore:
        try:
            async for event in _yield_sdk_events(conversation_prompt, options):
                if event.type == "content":
                    total_content += event.content or ""
                if event.type == "done":
                    got_done = True
                yield event

            # Fallback done event if SDK didn't emit ResultMessage
            if not got_done:
                yield StreamEvent(
                    type="done",
                    input_tokens=0,
                    output_tokens=len(total_content) // 4,
                    finish_reason="end_turn",
                )

        except asyncio.CancelledError:
            # CancelledError is BaseException (not Exception) in Python 3.9+.
            # The Claude Agent SDK's internal cancel scope can raise this when
            # the query subprocess terminates.  Emit a done event so the SSE
            # stream completes gracefully instead of terminating abruptly.
            logger.warning("Claude SDK stream cancelled (cancel scope); emitting fallback done")
            if not got_done:
                yield StreamEvent(
                    type="done",
                    input_tokens=0,
                    output_tokens=len(total_content) // 4,
                    finish_reason="end_turn",
                )

        except TimeoutError:
            logger.error("Claude OAuth stream timeout: request exceeded 300s")
            yield StreamEvent(type="error", error="Request timeout exceeded 300s")
            if not got_done:
                yield StreamEvent(
                    type="done",
                    input_tokens=0,
                    output_tokens=len(total_content) // 4,
                    finish_reason="end_turn",
                )

        except Exception as e:
            logger.error(f"Claude OAuth stream error: {e}")
            yield StreamEvent(type="error", error=str(e))
            if not got_done:
                yield StreamEvent(
                    type="done",
                    input_tokens=0,
                    output_tokens=len(total_content) // 4,
                    finish_reason="end_turn",
                )
