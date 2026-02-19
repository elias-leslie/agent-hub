"""Streaming logic for Claude adapter."""

import logging
from collections.abc import AsyncIterator
from typing import Any

from app.adapters.base import Message, StreamEvent
from app.adapters.claude_utils import build_claude_prompt
from app.services.tools.project_env import build_venv_env_overlay

logger = logging.getLogger(__name__)


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
    try:
        async for event in _yield_sdk_events(full_prompt, options):
            total_content += event.content or ""
            yield event

        # NOTE: The Claude Agent SDK streaming path does not expose actual
        # token counts. output_tokens is estimated as len(content) // 4.
        # See claude_oauth.py for ResultMessage.usage extraction when available.
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
