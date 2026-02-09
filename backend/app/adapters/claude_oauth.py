"""OAuth completion logic for Claude adapter."""

import asyncio
import json
import logging
import time
from typing import Any

from app.adapters.base import CompletionResult, Message, ProviderError
from app.adapters.claude_utils import extract_json_from_response, get_claude_thinking_budget

logger = logging.getLogger(__name__)


async def complete_oauth(
    messages: list[Message],
    model: str,
    cli_path: str,
    model_map: dict[str, str],
    provider_name: str,
    **kwargs: Any,
) -> CompletionResult:
    """Complete using OAuth via Claude Agent SDK.

    For structured output (JSON mode), uses native SDK output_format parameter
    which enforces JSON schema validation via StructuredOutput tool.
    """
    from claude_agent_sdk import ClaudeAgentOptions, ClaudeSDKClient
    from claude_agent_sdk.types import AssistantMessage, TextBlock

    start_time = time.time()

    # Map model to SDK short name
    sdk_model = model_map.get(model, model)

    # Check for structured output (JSON mode) request
    response_format = kwargs.get("response_format")
    json_mode = response_format is not None and response_format.get("type") == "json_object"
    json_schema = response_format.get("schema") if json_mode and response_format else None

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
    if not full_prompt.strip():
        full_prompt = "Hello"

    # Extended thinking support via OAuth
    thinking_budget = get_claude_thinking_budget(kwargs.get("thinking_level"))

    # Build SDK options
    sdk_options: dict[str, Any] = {
        "cwd": kwargs.get("working_dir", "."),
        "permission_mode": "bypassPermissions",  # For simple queries
        "cli_path": cli_path,
        "model": sdk_model,
        "max_thinking_tokens": thinking_budget,  # Extended thinking via OAuth
    }

    # Native structured output via SDK output_format (preferred approach)
    # SDK uses StructuredOutput tool internally for schema validation
    if json_mode and json_schema:
        sdk_options["output_format"] = {
            "type": "json_schema",
            "schema": json_schema,
        }
        # Structured output requires extra turn for tool response
        sdk_options["max_turns"] = 2
        logger.info("OAuth: Structured output enabled via native SDK output_format")

    options = ClaudeAgentOptions(**sdk_options)

    content_parts = []
    thinking_parts = []
    structured_output: dict[str, Any] | None = None
    try:
        client = ClaudeSDKClient(options=options)
        async with client:
            # Application-level timeout for OAuth (300s for agentic calls with large context)
            await asyncio.wait_for(client.query(full_prompt), timeout=300.0)

            msg: Any
            async for msg in client.receive_response():
                msg_type = type(msg).__name__

                # Extract thinking blocks (ThinkingBlock or type="thinking")
                if msg_type == "ThinkingBlock" or (
                    hasattr(msg, "type") and msg.type == "thinking"
                ):
                    thinking_text = getattr(msg, "thinking", "") or getattr(msg, "text", "")
                    if thinking_text:
                        thinking_parts.append(thinking_text)
                        logger.info(f"Claude OAuth thinking: {len(thinking_text)} chars")

                # Check for StructuredOutput tool use block (SDK output_format mechanism)
                if msg_type == "ToolUseBlock" or (
                    hasattr(msg, "type") and msg.type == "tool_use"
                ):
                    tool_name = getattr(msg, "name", "")
                    if tool_name == "StructuredOutput":
                        tool_input = getattr(msg, "input", {})
                        if tool_input:
                            structured_output = tool_input
                            logger.info("OAuth: Extracted structured output from ToolUseBlock")

                # Extract text content from AssistantMessage
                if isinstance(msg, AssistantMessage):
                    for block in msg.content:
                        if isinstance(block, TextBlock):
                            content_parts.append(block.text)
                        # Check for StructuredOutput tool use within AssistantMessage content
                        block_type = type(block).__name__
                        if (
                            block_type == "ToolUseBlock"
                            or getattr(block, "type", "") == "tool_use"
                        ):
                            tool_name = getattr(block, "name", "")
                            if tool_name == "StructuredOutput":
                                tool_input = getattr(block, "input", {})
                                if tool_input and structured_output is None:
                                    structured_output = tool_input
                                    logger.info(
                                        "OAuth: Extracted structured output from AssistantMessage content"
                                    )
                        # Also check for thinking blocks within content
                        if (
                            block_type == "ThinkingBlock"
                            or getattr(block, "type", "") == "thinking"
                        ):
                            thinking_text = getattr(block, "thinking", "") or getattr(
                                block, "text", ""
                            )
                            if thinking_text and thinking_text not in thinking_parts:
                                thinking_parts.append(thinking_text)

                # Check for structured_output attribute on ResultMessage
                if (
                    hasattr(msg, "structured_output")
                    and msg.structured_output
                    and structured_output is None
                ):
                    structured_output = msg.structured_output
                    logger.info("OAuth: Extracted structured output from ResultMessage")

        duration_ms = int((time.time() - start_time) * 1000)
        content = "".join(content_parts)
        thinking_content = "\n".join(thinking_parts) if thinking_parts else None

        # For structured output, use the extracted structured data
        if json_mode:
            if structured_output:
                # Native SDK structured output succeeded
                content = json.dumps(structured_output, indent=2)
                logger.info(f"OAuth: Using native structured output ({len(content)} chars)")
            elif content:
                # Fallback: Try to extract JSON from text response
                content = extract_json_from_response(content)
                logger.info("OAuth: Falling back to prompt-based JSON extraction")

        if thinking_content:
            logger.info(
                f"Claude OAuth response: {duration_ms}ms, {len(content)} chars, thinking: {len(thinking_content)} chars"
            )
        else:
            logger.info(f"Claude OAuth response: {duration_ms}ms, {len(content)} chars")

        # Estimate tokens from content length
        estimated_output_tokens = len(content) // 4
        thinking_tokens_estimate = len(thinking_content) // 4 if thinking_content else None

        return CompletionResult(
            content=content,
            model=f"claude-{sdk_model}",
            provider=provider_name,
            input_tokens=0,  # OAuth doesn't expose this
            output_tokens=estimated_output_tokens,
            finish_reason="end_turn",
            raw_response=None,
            cache_metrics=None,  # OAuth doesn't support prompt caching
            thinking_content=thinking_content,
            thinking_tokens=thinking_tokens_estimate,
        )

    except TimeoutError as e:
        logger.error("Claude OAuth timeout: request exceeded 300s")
        raise ProviderError(
            "Claude OAuth timeout: request exceeded 300s",
            provider=provider_name,
            retriable=True,
        ) from e

    except Exception as e:
        logger.error(f"Claude OAuth error: {e}")
        raise ProviderError(
            f"Claude OAuth error: {e}",
            provider=provider_name,
            retriable=True,
        ) from e
