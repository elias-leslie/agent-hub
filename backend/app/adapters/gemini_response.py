"""Response processing for Gemini adapter."""

import logging
from typing import Any

from app.adapters.base import CompletionResult, ProviderError, ToolCallResult

logger = logging.getLogger(__name__)


def process_response(response: Any, model: str, provider_name: str) -> CompletionResult:
    """Process API response and extract completion result.

    Args:
        response: Gemini API response object
        model: Model identifier
        provider_name: Provider name for error context

    Returns:
        CompletionResult with extracted content and metadata

    Raises:
        ProviderError: If response has error finish reason
    """
    content, thinking_content, tool_calls = _extract_parts(response)

    if not content and response.text:
        content = response.text

    input_tokens, output_tokens, thoughts_token_count = _extract_usage(response)
    finish_reason = _extract_finish_reason(response)

    _check_error_finish_reason(finish_reason, provider_name)

    thinking_tokens = thoughts_token_count or (len(thinking_content) // 4 if thinking_content else None)

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


def _extract_parts(response: Any) -> tuple[str, str, list[ToolCallResult]]:
    """Extract content, thinking, and tool calls from response parts.

    Args:
        response: Gemini API response

    Returns:
        Tuple of (content, thinking_content, tool_calls)
    """
    content = ""
    thinking_content = ""
    tool_calls: list[ToolCallResult] = []

    if not (
        response.candidates
        and response.candidates[0].content
        and response.candidates[0].content.parts
    ):
        return content, thinking_content, tool_calls

    for part in response.candidates[0].content.parts:
        if getattr(part, "thought", False) and part.text:
            thinking_content += part.text
        elif part.text:
            content += part.text
        elif part.function_call:
            tool_calls.append(_convert_function_call(part.function_call))

    return content, thinking_content, tool_calls


def _convert_function_call(fc: Any) -> ToolCallResult:
    """Convert Gemini function call to ToolCallResult.

    Args:
        fc: Gemini function call object

    Returns:
        ToolCallResult with id, name, and input
    """
    args = dict(fc.args) if fc.args else {}
    call_id = fc.id or fc.name or "unknown"
    return ToolCallResult(
        id=call_id,
        name=fc.name or "unknown",
        input=args,
    )


def _extract_usage(response: Any) -> tuple[int, int, int | None]:
    """Extract token usage from response.

    Args:
        response: Gemini API response

    Returns:
        Tuple of (input_tokens, output_tokens, thoughts_token_count)
    """
    if not response.usage_metadata:
        return 0, 0, None

    input_tokens = response.usage_metadata.prompt_token_count or 0
    output_tokens = response.usage_metadata.candidates_token_count or 0
    thoughts_token_count = getattr(response.usage_metadata, "thoughts_token_count", None)

    if thoughts_token_count:
        logger.info(f"Gemini thinking: {thoughts_token_count} tokens used")

    return input_tokens, output_tokens, thoughts_token_count


def _extract_finish_reason(response: Any) -> str | None:
    """Extract finish reason from response.

    Args:
        response: Gemini API response

    Returns:
        Finish reason as string, or None
    """
    if response.candidates and response.candidates[0].finish_reason:
        return str(response.candidates[0].finish_reason)
    return None


def _check_error_finish_reason(finish_reason: str | None, provider_name: str) -> None:
    """Check for error finish reasons and raise if found.

    Args:
        finish_reason: Finish reason to check
        provider_name: Provider name for error context

    Raises:
        ProviderError: If finish reason indicates an error
    """
    if not finish_reason:
        return

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

    if finish_reason not in error_finish_reasons:
        return

    error_msg = f"Gemini returned error finish_reason: {finish_reason}"
    logger.warning(error_msg)
    raise ProviderError(
        error_msg,
        provider=provider_name,
        retriable=finish_reason in {"FinishReason.MALFORMED_FUNCTION_CALL", "MALFORMED_FUNCTION_CALL"},
    )
