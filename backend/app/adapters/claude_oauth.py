"""OAuth completion logic for Claude adapter."""

import asyncio
import json
import logging
import time
from typing import Any

from app.adapters.base import CacheMetrics, CompletionResult, Message, ProviderError
from app.adapters.claude_utils import (
    _sdk_semaphore,
    build_sdk_options,
    extract_block_content,
    extract_json_from_response,
    extract_system_and_conversation,
)

logger = logging.getLogger(__name__)


def _process_assistant_blocks(msg: Any, content_parts: list[str], thinking_parts: list[str]) -> dict[str, Any] | None:
    """Process content blocks from an AssistantMessage, returning any structured output found."""
    structured_output = None
    for block in msg.content:
        extracted = extract_block_content(block)
        if extracted["type"] == "text":
            content_parts.append(extracted["text"])
        elif extracted["type"] == "thinking":
            thinking = extracted["thinking"]
            if thinking and thinking not in thinking_parts:
                thinking_parts.append(thinking)
        if "structured_output" in extracted:
            structured_output = extracted["structured_output"]
    return structured_output


def _extract_cache_metrics(msg: Any) -> CacheMetrics | None:
    """Extract cache metrics from an SDK message's usage data."""
    usage = getattr(msg, "usage", None)
    if not usage:
        return None
    if isinstance(usage, dict):
        creation, read = usage.get("cache_creation_input_tokens", 0) or 0, usage.get("cache_read_input_tokens", 0) or 0
    else:
        creation = getattr(usage, "cache_creation_input_tokens", 0) or 0
        read = getattr(usage, "cache_read_input_tokens", 0) or 0
    return CacheMetrics(cache_creation_input_tokens=creation, cache_read_input_tokens=read) if (creation or read) else None


async def _process_response_stream(
    client: Any, content_parts: list[str], thinking_parts: list[str],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, CacheMetrics | None]:
    """Process response stream; return (structured_output, usage, cache_metrics)."""
    from claude_agent_sdk.types import AssistantMessage, ResultMessage
    structured_output = None
    usage: dict[str, Any] | None = None
    cache_metrics: CacheMetrics | None = None
    async for msg in client.receive_response():
        extracted = extract_block_content(msg)
        if extracted["type"] == "text":
            content_parts.append(extracted["text"])
        elif extracted["type"] == "thinking":
            thinking_parts.append(extracted["thinking"])
            logger.info(f"Claude OAuth thinking: {len(extracted['thinking'])} chars")
        if "structured_output" in extracted:
            structured_output = extracted["structured_output"]
        if isinstance(msg, AssistantMessage):
            structured_output = _process_assistant_blocks(msg, content_parts, thinking_parts) or structured_output
        if hasattr(msg, "structured_output") and msg.structured_output and not structured_output:
            structured_output = msg.structured_output
            logger.info("OAuth: Extracted structured output from ResultMessage")
        if isinstance(msg, ResultMessage) and msg.usage:
            usage = msg.usage
            logger.info(f"OAuth: SDK ResultMessage usage data: {usage}")
        if cache_metrics is None:
            cache_metrics = _extract_cache_metrics(msg)
    return structured_output, usage, cache_metrics


def _build_result(
    content_parts: list[str], thinking_parts: list[str], structured_output: dict[str, Any] | None,
    usage: dict[str, Any] | None, cache_metrics: CacheMetrics | None,
    json_mode: bool, sdk_model: str, provider_name: str, start_time: float,
) -> CompletionResult:
    raw_content = "".join(content_parts)
    content = (json.dumps(structured_output, indent=2) if structured_output else extract_json_from_response(raw_content)) if json_mode else raw_content
    if json_mode:
        logger.info(f"OAuth: {'Native' if structured_output else 'Fallback'} JSON ({len(content)} chars)")
    thinking_content = "\n".join(thinking_parts) if thinking_parts else None
    input_tokens = (usage.get("input_tokens", 0) if usage else 0) or 0
    output_tokens = (usage.get("output_tokens", 0) if usage else 0) or len(content) // 4
    duration_ms = int((time.time() - start_time) * 1000)
    cache_info = f", cache_hit_rate={cache_metrics.cache_hit_rate:.1%}" if cache_metrics else ""
    token_info = " (from SDK)" if usage else " (estimated)"
    thinking_info = f", thinking: {len(thinking_content)} chars" if thinking_content else ""
    logger.info(f"Claude OAuth: {duration_ms}ms, {len(content)} chars, tokens={input_tokens}/{output_tokens}{token_info}{cache_info}{thinking_info}")
    return CompletionResult(
        content=content, model=f"claude-{sdk_model}", provider=provider_name,
        input_tokens=input_tokens, output_tokens=output_tokens, finish_reason="end_turn",
        raw_response=None, cache_metrics=cache_metrics, thinking_content=thinking_content,
        thinking_tokens=len(thinking_content) // 4 if thinking_content else None,
    )


async def complete_oauth(
    messages: list[Message], model: str, cli_path: str,
    model_map: dict[str, str], provider_name: str, **kwargs: Any,
) -> CompletionResult:
    """Complete using OAuth via Claude Agent SDK with native JSON mode support.
    Accepts ``cache_retention`` via kwargs for forward-compatibility (SDK does not
    yet support cache_control headers). Cache usage data surfaced via CacheMetrics.
    """
    from claude_agent_sdk import ClaudeSDKClient
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
    json_mode = response_format.get("type") == "json_object"
    json_schema = response_format.get("schema") if json_mode else None
    system_prompt, conversation_prompt = extract_system_and_conversation(messages)
    options, _ = build_sdk_options(
        cli_path=cli_path, model=model, model_map=model_map,
        working_dir=kwargs.get("working_dir"), json_mode=json_mode,
        json_schema=json_schema, thinking_level=kwargs.get("thinking_level"),
        system_prompt=system_prompt,
    )
    content_parts: list[str] = []
    thinking_parts: list[str] = []
    try:
        client = ClaudeSDKClient(options=options)
        async with _sdk_semaphore, client:
            await asyncio.wait_for(client.query(conversation_prompt), timeout=300.0)
            structured_output, usage, cache_metrics = await _process_response_stream(
                client, content_parts, thinking_parts,
            )
        return _build_result(
            content_parts, thinking_parts, structured_output, usage,
            cache_metrics, json_mode, sdk_model, provider_name, start_time,
        )
    except TimeoutError as e:
        raise ProviderError("Claude OAuth timeout: request exceeded 300s", provider=provider_name, retriable=True) from e
    except Exception as e:
        raise ProviderError(f"Claude OAuth error: {e}", provider=provider_name, retriable=True) from e
