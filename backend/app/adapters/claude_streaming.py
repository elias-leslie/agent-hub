"""Streaming logic for Claude adapter."""

import logging
from collections.abc import AsyncIterator
from typing import Any

from app.adapters.base import Message, StreamEvent
from app.services.tools.project_env import build_venv_env_overlay

logger = logging.getLogger(__name__)


async def stream_oauth(
    messages: list[Message],
    model: str,
    cli_path: str,
    model_map: dict[str, str],
    **kwargs: Any,
) -> AsyncIterator[StreamEvent]:
    """Stream using OAuth via Claude Agent SDK."""
    from claude_agent_sdk import ClaudeAgentOptions, query
    from claude_agent_sdk.types import AssistantMessage, TextBlock

    # Map model to SDK short name
    sdk_model = model_map.get(model, model)

    # Build prompt from messages
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

    full_prompt = "\n".join(system_parts + prompt_parts)

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
        async def _stream_with_timeout() -> AsyncIterator[StreamEvent]:
            nonlocal total_content
            async for message in query(prompt=full_prompt, options=options):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            total_content += block.text
                            yield StreamEvent(type="content", content=block.text)

        async for event in _stream_with_timeout():
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
