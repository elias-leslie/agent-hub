"""OAuth completion logic for Claude adapter."""

import asyncio
import json
import logging
import time
from typing import Any

from app.adapters.base import CompletionResult, Message, ProviderError
from app.adapters.claude_utils import extract_json_from_response, get_claude_thinking_budget

logger = logging.getLogger(__name__)


def _build_prompt_from_messages(messages: list[Message]) -> str:
    """Build full prompt from message list."""
    parts: list[str] = []
    for msg in messages:
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        if msg.role == "system":
            parts.insert(0, content)
        elif msg.role == "user":
            parts.append(f"User: {content}")
        elif msg.role == "assistant":
            parts.append(f"Assistant: {content}")
    return "\n".join(parts) or "Hello"


def _build_sdk_options(cli_path: str, sdk_model: str, json_mode: bool, json_schema: dict[str, Any] | None, kwargs: dict[str, Any]) -> Any:
    """Build ClaudeAgentOptions with JSON mode support."""
    from claude_agent_sdk import ClaudeAgentOptions

    opts = {
        "cwd": kwargs.get("working_dir", "."),
        "permission_mode": "bypassPermissions",
        "cli_path": cli_path,
        "model": sdk_model,
        "max_thinking_tokens": get_claude_thinking_budget(kwargs.get("thinking_level")),
    }
    if json_mode and json_schema:
        opts.update({"output_format": {"type": "json_schema", "schema": json_schema}, "max_turns": 2})
        logger.info("OAuth: Structured output enabled via native SDK output_format")
    return ClaudeAgentOptions(**opts)


def _extract_from_block(block: Any) -> tuple[str | None, str | None, dict[str, Any] | None]:
    """Extract text, thinking, and structured output from a message block."""
    from claude_agent_sdk.types import TextBlock

    btype = type(block).__name__
    text = block.text if isinstance(block, TextBlock) else None
    thinking = (getattr(block, "thinking", "") or getattr(block, "text", "")) if btype == "ThinkingBlock" or getattr(block, "type", "") == "thinking" else None
    structured = None
    if (btype == "ToolUseBlock" or getattr(block, "type", "") == "tool_use") and getattr(block, "name", "") == "StructuredOutput" and (structured := (getattr(block, "input", {}) or None)):
        logger.info("OAuth: Extracted structured output from message block")
    return text, thinking, structured


async def _process_response_stream(client: Any, content_parts: list[str], thinking_parts: list[str]) -> dict[str, Any] | None:
    """Process response stream from SDK client."""
    from claude_agent_sdk.types import AssistantMessage

    structured_output = None
    async for msg in client.receive_response():
        text, thinking, structured = _extract_from_block(msg)
        if text:
            content_parts.append(text)
        if thinking:
            thinking_parts.append(thinking)
            logger.info(f"Claude OAuth thinking: {len(thinking)} chars")
        structured_output = structured or structured_output

        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                text, thinking, structured = _extract_from_block(block)
                if text:
                    content_parts.append(text)
                if thinking and thinking not in thinking_parts:
                    thinking_parts.append(thinking)
                structured_output = structured or structured_output

        if hasattr(msg, "structured_output") and msg.structured_output and not structured_output:
            structured_output = msg.structured_output
            logger.info("OAuth: Extracted structured output from ResultMessage")
    return structured_output


async def complete_oauth(messages: list[Message], model: str, cli_path: str, model_map: dict[str, str], provider_name: str, **kwargs: Any) -> CompletionResult:
    """Complete using OAuth via Claude Agent SDK with native JSON mode support."""
    from claude_agent_sdk import ClaudeSDKClient

    start_time = time.time()
    sdk_model = model_map.get(model, model)
    response_format = kwargs.get("response_format", {})
    json_mode, json_schema = response_format.get("type") == "json_object", response_format.get("schema") if response_format.get("type") == "json_object" else None

    options = _build_sdk_options(cli_path, sdk_model, json_mode, json_schema, kwargs)
    content_parts: list[str] = []
    thinking_parts: list[str] = []
    try:
        client = ClaudeSDKClient(options=options)
        async with client:
            await asyncio.wait_for(client.query(_build_prompt_from_messages(messages)), timeout=300.0)
            structured_output = await _process_response_stream(client, content_parts, thinking_parts)

        content = "".join(content_parts)
        thinking_content = "\n".join(thinking_parts) if thinking_parts else None

        if json_mode:
            content = json.dumps(structured_output, indent=2) if structured_output else extract_json_from_response(content)
            logger.info(f"OAuth: {'Native' if structured_output else 'Fallback'} JSON ({len(content)} chars)")

        duration_ms = int((time.time() - start_time) * 1000)
        logger.info(f"Claude OAuth: {duration_ms}ms, {len(content)} chars" + (f", thinking: {len(thinking_content)} chars" if thinking_content else ""))

        return CompletionResult(
            content=content, model=f"claude-{sdk_model}", provider=provider_name,
            input_tokens=0, output_tokens=len(content) // 4, finish_reason="end_turn",
            raw_response=None, cache_metrics=None, thinking_content=thinking_content,
            thinking_tokens=len(thinking_content) // 4 if thinking_content else None,
        )
    except TimeoutError as e:
        error_msg = "Claude OAuth timeout: request exceeded 300s"
        logger.error(error_msg)
        raise ProviderError(error_msg, provider=provider_name, retriable=True) from e
    except Exception as e:
        error_msg = f"Claude OAuth error: {e}"
        logger.error(error_msg)
        raise ProviderError(error_msg, provider=provider_name, retriable=True) from e
