"""Tool handling with hooks for Claude adapter."""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from app.adapters.base import Message, ProviderError
from app.adapters.claude_tools_helpers import (
    _build_can_use_tool,
    _build_sdk_options,
    _build_tool_hooks,
)

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


def _build_prompt_string(messages: list[Message]) -> str:
    """Build a flat prompt string from a list of messages."""
    system_parts: list[str] = []
    prompt_parts: list[str] = []
    for msg_item in messages:
        content_str = (
            msg_item.content if isinstance(msg_item.content, str) else str(msg_item.content)
        )
        if msg_item.role == "system":
            system_parts.append(content_str)
        elif msg_item.role == "user":
            prompt_parts.append(content_str)
    return "\n".join(system_parts + prompt_parts)


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
    after_tool_callback: Callable[[str, dict[str, Any], str, int | None], Awaitable[None]] | None,
    **kwargs: Any,
) -> AsyncIterator[tuple[Any, str | None]]:
    """Generate with native tool calling using SDK-native permission mechanisms."""
    hooks_typed = _build_tool_hooks(after_tool_callback)
    options, use_streaming_prompt = _build_sdk_options(
        model, model_map, working_dir, cli_path, hooks_typed,
        yolo_mode, permission_checker, resume_session_id,
    )
    full_prompt = _build_prompt_string(messages)
    prompt: str | Any = await _wrap_prompt_as_stream(full_prompt) if use_streaming_prompt else full_prompt
    async for item in _stream_sdk_messages(prompt, options, provider_name):
        yield item


# Re-export helpers so existing callers importing from this module continue to work
__all__ = [
    "_build_can_use_tool",
    "_build_prompt_string",
    "_build_sdk_options",
    "_build_tool_hooks",
    "_wrap_prompt_as_stream",
    "complete_with_tools",
]
