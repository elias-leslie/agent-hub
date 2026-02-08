"""Utility functions for Gemini adapter."""

import base64
import logging
import re
from typing import Any, NoReturn

from google.genai import types

from app.adapters.base import CompletionResult, Message, ProviderError, ToolCallResult
from app.adapters.gemini_thinking import get_thinking_level

logger = logging.getLogger(__name__)


def build_parts(content: str | list[dict[str, Any]]) -> list[types.Part]:
    """Build Gemini parts from content.

    Args:
        content: Either a string or list of content blocks (text/image).

    Returns:
        List of Gemini Part objects.
    """
    if isinstance(content, str):
        return [types.Part(text=content)]

    parts: list[types.Part] = []
    for block in content:
        if isinstance(block, str):
            parts.append(types.Part(text=block))
        elif isinstance(block, dict):
            block_type = block.get("type")
            if block_type == "text":
                parts.append(types.Part(text=block.get("text", "")))
            elif block_type == "image":
                # Extract image data from source
                source = block.get("source", {})
                if source.get("type") == "base64":
                    media_type = source.get("media_type", "image/png")
                    data = source.get("data", "")
                    # Gemini expects raw bytes for inline_data
                    image_bytes = base64.b64decode(data)
                    parts.append(types.Part.from_bytes(data=image_bytes, mime_type=media_type))
    return parts


def convert_messages(
    messages: list[Message],
) -> tuple[str | None, list[types.Content]]:
    """Convert messages to Gemini format.

    Args:
        messages: List of Message objects

    Returns:
        Tuple of (system_instruction, contents)
    """
    system_instruction: str | None = None
    contents: list[types.Content] = []

    for msg in messages:
        if msg.role == "system":
            # System messages must be strings
            system_instruction = msg.content if isinstance(msg.content, str) else str(msg.content)
        else:
            # Map roles: user -> user, assistant -> model
            role = "model" if msg.role == "assistant" else "user"
            parts = build_parts(msg.content)
            contents.append(types.Content(role=role, parts=parts))

    return system_instruction, contents


def build_config(
    temperature: float,
    max_tokens: int | None,
    model: str,
    response_format: dict[str, Any] | None,
    system_instruction: str | None,
    tools: Any,
    **kwargs: Any,
) -> types.GenerateContentConfig:
    """Build GenerateContentConfig from parameters."""
    config_params: dict[str, Any] = {
        "temperature": temperature,
        "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
    }

    if max_tokens is not None:
        config_params["max_output_tokens"] = max_tokens

    config = types.GenerateContentConfig(**config_params)

    # Handle structured output (JSON mode)
    if response_format and response_format.get("type") == "json_object":
        config.response_mime_type = "application/json"
        json_schema = response_format.get("schema")
        if json_schema:
            config.response_schema = json_schema
            logger.info("Gemini structured output enabled with JSON schema")
        else:
            logger.info("Gemini structured output enabled (JSON mode without schema)")

    # Gemini 3 thinking config
    thinking_level = get_thinking_level(model, kwargs.get("thinking_level"))
    if thinking_level:
        config.thinking_config = types.ThinkingConfig(thinking_level=thinking_level)
        logger.debug(f"Gemini thinking_level={thinking_level} for model={model}")

    if system_instruction:
        config.system_instruction = system_instruction

    if tools:
        config.tools = tools

    return config


def process_response(response: Any, model: str, provider_name: str) -> CompletionResult:
    """Process API response and extract completion result."""
    content = ""
    thinking_content = ""
    tool_calls: list[ToolCallResult] = []

    if (
        response.candidates
        and response.candidates[0].content
        and response.candidates[0].content.parts
    ):
        for part in response.candidates[0].content.parts:
            # Check if this is a thinking part
            if getattr(part, "thought", False) and part.text:
                thinking_content += part.text
            elif part.text:
                content += part.text
            elif part.function_call:
                fc = part.function_call
                args = dict(fc.args) if fc.args else {}
                call_id = fc.id or fc.name or "unknown"
                tool_calls.append(
                    ToolCallResult(
                        id=call_id,
                        name=fc.name or "unknown",
                        input=args,
                    )
                )

    # Fallback to response.text if no parts
    if not content and response.text:
        content = response.text

    # Extract token counts
    input_tokens = 0
    output_tokens = 0
    thoughts_token_count = None
    if response.usage_metadata:
        input_tokens = response.usage_metadata.prompt_token_count or 0
        output_tokens = response.usage_metadata.candidates_token_count or 0
        thoughts_token_count = getattr(response.usage_metadata, "thoughts_token_count", None)
        if thoughts_token_count:
            logger.info(f"Gemini thinking: {thoughts_token_count} tokens used")

    # Determine finish reason
    finish_reason = None
    if response.candidates and response.candidates[0].finish_reason:
        finish_reason = str(response.candidates[0].finish_reason)

    # Handle error finish reasons
    error_finish_reasons = {
        "FinishReason.MALFORMED_FUNCTION_CALL",
        "MALFORMED_FUNCTION_CALL",
        "FinishReason.SAFETY",
        "SAFETY",
        "FinishReason.RECITATION",
        "RECITATION",
        "FinishReason.OTHER",
        "OTHER",
    }
    if finish_reason in error_finish_reasons:
        error_msg = f"Gemini returned error finish_reason: {finish_reason}"
        logger.warning(error_msg)
        raise ProviderError(
            error_msg,
            provider=provider_name,
            retriable=finish_reason
            in {"FinishReason.MALFORMED_FUNCTION_CALL", "MALFORMED_FUNCTION_CALL"},
        )

    # Use API-provided thinking tokens if available, otherwise estimate
    thinking_tokens = thoughts_token_count
    if not thinking_tokens and thinking_content:
        thinking_tokens = len(thinking_content) // 4

    return CompletionResult(
        content=content,
        model=model,
        provider=provider_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        finish_reason=finish_reason,
        raw_response=response,
        tool_calls=tool_calls if tool_calls else None,
        thinking_content=thinking_content if thinking_content else None,
        thinking_tokens=thinking_tokens,
    )


def handle_error(e: Exception, provider_name: str) -> NoReturn:
    """Handle Gemini API errors and raise appropriate exceptions.

    Args:
        e: The caught exception
        provider_name: Provider name for error context

    Raises:
        RateLimitError: For rate limit/quota errors
        AuthenticationError: For auth errors
        ProviderError: For other errors
    """
    from app.adapters.base import AuthenticationError, RateLimitError

    error_str = str(e).lower()

    # Extract status code from error string
    # Gemini SDK errors often look like: "429 Too Many Requests", "503 Service Unavailable"
    # or "RPC error: code = 429 message = ..."
    status_code = None
    match = re.search(r"\b(4\d{2}|5\d{2})\b", str(e))
    if match:
        status_code = int(match.group(1))

    # Check for rate limit errors
    if status_code == 429 or "rate" in error_str or "quota" in error_str:
        logger.warning(f"Gemini rate limit: {e}")
        raise RateLimitError(provider_name) from e

    # Check for auth errors
    if status_code in (401, 403) or "api key" in error_str:
        logger.error(f"Gemini auth error: {e}")
        raise AuthenticationError(provider_name) from e

    # Generic provider error
    logger.error(f"Gemini API error: {e}")

    # All 5xx errors are retriable
    retriable = False
    if status_code and 500 <= status_code < 600:
        retriable = True
    elif any(code in str(e) for code in ("500", "502", "503", "504")):
        # Fallback for substrings
        retriable = True

    raise ProviderError(
        str(e),
        provider=provider_name,
        retriable=retriable,
        status_code=status_code,
    ) from e
