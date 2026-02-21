"""Streaming logic for Claude adapter."""

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from app.adapters.base import Message, StreamEvent
from app.adapters.claude_utils import build_claude_prompt
from app.services.tools.project_env import build_venv_env_overlay

logger = logging.getLogger(__name__)


async def _yield_sdk_events(full_prompt: str, options: Any) -> AsyncIterator[StreamEvent]:
    """Yield StreamEvents from the Claude Agent SDK query.

    Emits content, tool_use, and tool_result events so the shared streaming
    loop can track tool execution without re-executing tools the CLI already ran.
    """
    from claude_agent_sdk import query
    from claude_agent_sdk.types import (
        AssistantMessage,
        ResultMessage,
        TextBlock,
        ToolResultBlock,
        ToolUseBlock,
    )

    async for message in query(prompt=full_prompt, options=options):
        if isinstance(message, ResultMessage):
            # Final SDK message with usage stats
            usage = message.usage or {}
            yield StreamEvent(
                type="done",
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                finish_reason="end_turn",
            )
            return
        if not isinstance(message, AssistantMessage):
            continue
        for block in message.content:
            if isinstance(block, TextBlock):
                yield StreamEvent(type="content", content=block.text)
            elif isinstance(block, ToolUseBlock):
                yield StreamEvent(
                    type="tool_use",
                    tool_id=block.id,
                    tool_name=block.name,
                    tool_input=block.input if isinstance(block.input, dict) else {},
                )
            elif isinstance(block, ToolResultBlock):
                content = block.content if isinstance(block.content, str) else str(block.content or "")
                yield StreamEvent(
                    type="tool_result",
                    tool_id=block.tool_use_id,
                    content=content,
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
    from claude_agent_sdk import ClaudeAgentOptions

    # cache_retention is accepted for forward-compatibility but is not yet
    # actionable through the Claude Agent SDK streaming path.
    cache_retention = kwargs.pop("cache_retention", "none")
    if cache_retention != "none":
        logger.debug(
            "cache_retention=%s requested but Claude Agent SDK streaming does "
            "not support cache_control headers; parameter ignored",
            cache_retention,
        )

    sdk_model = model_map.get(model, model)
    full_prompt = build_claude_prompt(messages)
    cwd = kwargs.get("working_dir", ".")
    options = ClaudeAgentOptions(
        cwd=cwd,
        permission_mode="bypassPermissions",
        cli_path=cli_path,
        model=sdk_model,
        env=build_venv_env_overlay(cwd),
    )

    total_content = ""
    got_done = False
    try:
        async for event in _yield_sdk_events(full_prompt, options):
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

    except Exception as e:
        logger.error(f"Claude OAuth stream error: {e}")
        yield StreamEvent(type="error", error=str(e))
