"""Tool handling for Claude adapter."""

import logging
from collections.abc import AsyncIterator
from typing import Any

from app.adapters.base import Message, ProviderError
from app.adapters.claude_tools_helpers import _build_sdk_options
from app.adapters.claude_utils import build_claude_prompt

logger = logging.getLogger(__name__)


async def _wrap_prompt_as_stream(prompt: str) -> Any:
    """Wrap a string prompt as an async iterable for SDK streaming mode."""

    async def _stream() -> Any:
        yield {
            "type": "user",
            "message": {"role": "user", "content": prompt},
            "parent_tool_use_id": None,
            "session_id": None,
        }

    return _stream()


async def _stream_sdk_messages(
    prompt: str | Any,
    options: Any,
    provider_name: str,
) -> AsyncIterator[tuple[Any, str | None]]:
    """Yield (message, session_id) pairs from claude_agent_sdk query."""
    from claude_agent_sdk import query

    session_id: str | None = None
    try:
        async for message in query(prompt=prompt, options=options):
            if hasattr(message, "subtype") and message.subtype == "init" and hasattr(message, "data"):
                session_id = message.data.get("session_id")  # ty: ignore[unresolved-attribute]
                if session_id:
                    logger.info(f"Claude SDK session ID: {session_id}")
            yield (message, session_id)
    except Exception as e:
        logger.error(f"Claude tool error: {e}")
        raise ProviderError(f"Claude tool error: {e}", provider=provider_name, retriable=True) from e


async def complete_with_tools(
    messages: list[Message],
    model: str,
    tools: list[dict[str, Any]],
    yolo_mode: bool,
    permission_checker: Any | None,
    working_dir: str | None,
    resume_session_id: str | None,
    cli_path: str,
    model_map: dict[str, str],
    provider_name: str,
    **kwargs: Any,
) -> AsyncIterator[tuple[Any, str | None]]:
    """Generate with native tool calling using SDK-native permission mechanisms."""
    options, use_streaming_prompt = _build_sdk_options(
        model, model_map, working_dir, cli_path,
        yolo_mode, permission_checker, resume_session_id,
    )
    full_prompt = build_claude_prompt(messages)
    prompt: str | Any = await _wrap_prompt_as_stream(full_prompt) if use_streaming_prompt else full_prompt
    async for item in _stream_sdk_messages(prompt, options, provider_name):
        yield item
