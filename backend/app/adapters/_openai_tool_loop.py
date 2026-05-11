"""Agentic tool-calling loop for OpenAI-compatible adapters.

Not part of the public API — import from openai_compat instead.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TYPE_CHECKING, Any

from app.adapters._openai_compat_helpers import (
    build_completion_params,
    convert_messages,
    execute_tool_calls,
    parse_completion_response,
)
from app.adapters.base import Message, StreamEvent
from app.constants.agent_limits import DEFAULT_AGENTIC_MAX_TURNS

if TYPE_CHECKING:
    from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

_EMPTY_FINAL_RESPONSE_MSG = (
    "You have finished tool work but have not produced a final user-facing response. "
    "Write the final response now. "
    "If no changes were needed, say so plainly. "
    "If changes were made, summarize the exact changes and evidence. "
    "Do not call more tools unless a missing fact blocks the response."
)


async def run_tool_loop(
    client: AsyncOpenAI,
    provider_name: str,
    model_id: str,
    messages: list[Message],
    tools: list[dict[str, Any]],
    tool_handler: Callable[[str, dict[str, Any]], Awaitable[str]],
    refresh_credentials: Callable[..., Awaitable[str | None]],
    max_turns: int = DEFAULT_AGENTIC_MAX_TURNS,
    temperature: float = 1.0,
    max_tokens: int | None = None,
    **kwargs: Any,
) -> AsyncIterator[StreamEvent]:
    """Run an agentic tool-calling loop over the OpenAI-compatible API.

    Yields StreamEvents for tool_use, tool_result, content, done, and error.
    """
    openai_messages: list[dict[str, Any]] = convert_messages(messages)
    extra_kwargs = {**kwargs, "tools": tools}
    empty_closeout_used = False

    for _turn in range(max_turns):
        await refresh_credentials()
        params = build_completion_params(model_id, openai_messages, temperature, max_tokens, extra_kwargs)
        try:
            response = await client.chat.completions.create(**params)
            result = parse_completion_response(response, provider_name)
        except Exception as e:
            logger.error("%s complete_with_tools error: %s", provider_name, e)
            yield StreamEvent(type="error", error=str(e))
            return

        if result.tool_calls:
            async for event in execute_tool_calls(result, openai_messages, tool_handler):
                yield event
            continue

        no_content = not (result.content or "").strip()
        if no_content and not empty_closeout_used and _turn + 1 < max_turns:
            openai_messages.append({"role": "user", "content": _EMPTY_FINAL_RESPONSE_MSG})
            empty_closeout_used = True
            continue

        if result.content:
            yield StreamEvent(type="content", content=result.content)
        yield StreamEvent(
            type="done",
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            finish_reason=result.finish_reason,
        )
        return

    yield StreamEvent(type="done", finish_reason="max_turns")
