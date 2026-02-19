"""Streaming logic for Claude adapter."""

import logging
from collections.abc import AsyncIterator
from typing import Any

from app.adapters.base import Message, StreamEvent
from app.services.tools.project_env import build_venv_env_overlay

logger = logging.getLogger(__name__)


def _build_prompt(messages: list[Message]) -> str:
    """Build a single prompt string from a list of messages."""
    system_parts: list[str] = []
    prompt_parts: list[str] = []
    for message in messages:
        content_str = (
            message.content if isinstance(message.content, str) else str(message.content)
        )
        if message.role == "system":
            system_parts.append(content_str)
        elif message.role == "user":
            prompt_parts.append(f"User: {content_str}")
        elif message.role == "assistant":
            prompt_parts.append(f"Assistant: {content_str}")
    return "\n".join(system_parts + prompt_parts)


async def _yield_sdk_events(full_prompt: str, options: Any) -> AsyncIterator[StreamEvent]:
    """Yield StreamEvents from the Claude Agent SDK query."""
    from claude_agent_sdk import query
    from claude_agent_sdk.types import AssistantMessage, TextBlock

    async for message in query(prompt=full_prompt, options=options):
        if not isinstance(message, AssistantMessage):
            continue
        for block in message.content:
            if not isinstance(block, TextBlock):
                continue
            yield StreamEvent(type="content", content=block.text)


async def stream_oauth(
    messages: list[Message],
    model: str,
    cli_path: str,
    model_map: dict[str, str],
    **kwargs: Any,
) -> AsyncIterator[StreamEvent]:
    """Stream using OAuth via Claude Agent SDK."""
    from claude_agent_sdk import ClaudeAgentOptions

    sdk_model = model_map.get(model, model)
    full_prompt = _build_prompt(messages)
    cwd = kwargs.get("working_dir", ".")
    options = ClaudeAgentOptions(
        cwd=cwd,
        permission_mode="bypassPermissions",
        cli_path=cli_path,
        model=sdk_model,
        env=build_venv_env_overlay(cwd),
    )

    total_content = ""
    try:
        async for event in _yield_sdk_events(full_prompt, options):
            total_content += event.content or ""
            yield event

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
