"""OAuth completion logic for Claude adapter."""

import asyncio
import json
import logging
import time
from typing import Any

from app.adapters.base import CacheMetrics, CompletionResult, Message, ProviderError
from app.adapters.claude_utils import (
    _sdk_semaphore,
    build_claude_prompt,
    extract_json_from_response,
    get_claude_thinking_budget,
)
from app.services.tools.project_env import build_venv_env_overlay

logger = logging.getLogger(__name__)


def _build_sdk_options(cli_path: str, sdk_model: str, json_mode: bool, json_schema: dict[str, Any] | None, kwargs: dict[str, Any]) -> Any:
    """Build ClaudeAgentOptions with JSON mode support."""
    from claude_agent_sdk import ClaudeAgentOptions

    cwd = kwargs.get("working_dir") or "."
    opts = {
        "cwd": cwd,
        "permission_mode": "bypassPermissions",
        "cli_path": cli_path,
        "model": sdk_model,
        "max_thinking_tokens": get_claude_thinking_budget(kwargs.get("thinking_level")),
        "env": build_venv_env_overlay(cwd),
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


def _process_assistant_blocks(msg: Any, content_parts: list[str], thinking_parts: list[str]) -> dict[str, Any] | None:
    """Process content blocks from an AssistantMessage, returning any structured output found."""
    structured_output = None
    for block in msg.content:
        text, thinking, structured = _extract_from_block(block)
        if text:
            content_parts.append(text)
        if thinking and thinking not in thinking_parts:
            thinking_parts.append(thinking)
        structured_output = structured or structured_output
    return structured_output


def _extract_cache_metrics(msg: Any) -> CacheMetrics | None:
    """Extract cache metrics from an SDK message's usage data.

    ResultMessage.usage is a dict with keys like ``cache_creation_input_tokens``
    and ``cache_read_input_tokens``.
    """
    usage = getattr(msg, "usage", None)
    if not usage:
        return None
    # usage is a dict — use .get(), not getattr()
    if isinstance(usage, dict):
        creation = usage.get("cache_creation_input_tokens", 0) or 0
        read = usage.get("cache_read_input_tokens", 0) or 0
    else:
        creation = getattr(usage, "cache_creation_input_tokens", 0) or 0
        read = getattr(usage, "cache_read_input_tokens", 0) or 0
    if creation or read:
        return CacheMetrics(cache_creation_input_tokens=creation, cache_read_input_tokens=read)
    return None


async def _process_response_stream(
    client: Any,
    content_parts: list[str],
    thinking_parts: list[str],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, CacheMetrics | None]:
    """Process response stream from SDK client.

    Returns:
        (structured_output, usage, cache_metrics) — structured_output is the
        parsed JSON output if found, usage is the token usage dict from the
        SDK's ResultMessage (if available), cache_metrics is populated when
        the SDK exposes prompt-caching usage data.
    """
    from claude_agent_sdk.types import AssistantMessage, ResultMessage

    structured_output = None
    usage: dict[str, Any] | None = None
    cache_metrics: CacheMetrics | None = None
    async for msg in client.receive_response():
        text, thinking, structured = _extract_from_block(msg)
        if text:
            content_parts.append(text)
        if thinking:
            thinking_parts.append(thinking)
            logger.info(f"Claude OAuth thinking: {len(thinking)} chars")
        structured_output = structured or structured_output

        if isinstance(msg, AssistantMessage):
            structured_output = _process_assistant_blocks(msg, content_parts, thinking_parts) or structured_output

        if hasattr(msg, "structured_output") and msg.structured_output and not structured_output:
            structured_output = msg.structured_output
            logger.info("OAuth: Extracted structured output from ResultMessage")

        # Capture token usage from the SDK's ResultMessage when available.
        # ResultMessage.usage is typed as dict[str, Any] | None and may contain
        # keys like "input_tokens" and "output_tokens" from the Anthropic API.
        if isinstance(msg, ResultMessage) and msg.usage:
            usage = msg.usage
            logger.info(f"OAuth: SDK ResultMessage usage data: {usage}")

        # Attempt to capture cache metrics from any message that carries usage data
        if cache_metrics is None:
            cache_metrics = _extract_cache_metrics(msg)

    return structured_output, usage, cache_metrics


async def complete_oauth(messages: list[Message], model: str, cli_path: str, model_map: dict[str, str], provider_name: str, **kwargs: Any) -> CompletionResult:
    """Complete using OAuth via Claude Agent SDK with native JSON mode support.

    Accepts ``cache_retention`` via kwargs ("none", "short", "long").  The
    Claude Agent SDK currently abstracts the HTTP layer so we cannot inject
    ``cache_control`` headers directly.  The parameter is accepted for
    forward-compatibility and will become actionable when a direct Anthropic
    API adapter is added.  If the SDK exposes cache usage data on response
    messages we populate ``CacheMetrics`` on the result.
    """
    from claude_agent_sdk import ClaudeSDKClient

    # cache_retention is accepted but not yet actionable via the SDK
    cache_retention = kwargs.pop("cache_retention", "none")
    if cache_retention != "none":
        logger.debug(
            "cache_retention=%s requested but Claude Agent SDK does not "
            "support cache_control headers; parameter stored for future use",
            cache_retention,
        )

    start_time = time.time()
    sdk_model = model_map.get(model, model)
    response_format = kwargs.get("response_format") or {}
    json_mode, json_schema = response_format.get("type") == "json_object", response_format.get("schema") if response_format.get("type") == "json_object" else None

    options = _build_sdk_options(cli_path, sdk_model, json_mode, json_schema, kwargs)
    content_parts: list[str] = []
    thinking_parts: list[str] = []
    try:
        client = ClaudeSDKClient(options=options)
        async with _sdk_semaphore, client:
            await asyncio.wait_for(client.query(build_claude_prompt(messages)), timeout=300.0)
            structured_output, usage, cache_metrics = await _process_response_stream(client, content_parts, thinking_parts)

        content = "".join(content_parts)
        thinking_content = "\n".join(thinking_parts) if thinking_parts else None

        if json_mode:
            content = json.dumps(structured_output, indent=2) if structured_output else extract_json_from_response(content)
            logger.info(f"OAuth: {'Native' if structured_output else 'Fallback'} JSON ({len(content)} chars)")

        # Use actual token counts from SDK ResultMessage.usage when available,
        # otherwise fall back to rough character-based estimate (chars // 4).
        # NOTE: The Claude Agent SDK's ResultMessage.usage dict may contain
        # "input_tokens" and "output_tokens" from the Anthropic API, but this
        # is not guaranteed across SDK versions. The fallback estimation is a
        # known limitation.
        input_tokens = (usage.get("input_tokens", 0) if usage else 0) or 0
        output_tokens = (usage.get("output_tokens", 0) if usage else 0) or len(content) // 4

        duration_ms = int((time.time() - start_time) * 1000)
        cache_info = f", cache_hit_rate={cache_metrics.cache_hit_rate:.1%}" if cache_metrics else ""
        token_info = " (from SDK)" if usage else " (estimated)"
        logger.info(f"Claude OAuth: {duration_ms}ms, {len(content)} chars, tokens={input_tokens}/{output_tokens}{token_info}{cache_info}" + (f", thinking: {len(thinking_content)} chars" if thinking_content else ""))

        return CompletionResult(
            content=content, model=f"claude-{sdk_model}", provider=provider_name,
            input_tokens=input_tokens, output_tokens=output_tokens, finish_reason="end_turn",
            raw_response=None, cache_metrics=cache_metrics, thinking_content=thinking_content,
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
