"""Completion API package."""

from .core import (
    CompletionInternalResult,
    complete_internal,
    get_or_create_session,
    save_messages,
    stream_completion,
    update_provider_metadata,
)
from .helpers import (
    clear_adapter_cache,
    extract_text_content,
    get_adapter,
    get_provider,
    is_error_response,
    normalize_content_for_storage,
    parse_mention,
    should_enable_thinking,
    validate_json_response,
)
from .schemas import (
    CacheInfo,
    CompletionRequest,
    CompletionResponse,
    ContainerInfo,
    ContextUsageInfo,
    EstimateRequest,
    EstimateResponse,
    MessageInput,
    OutputUsageInfo,
    ResponseFormat,
    StreamingChunk,
    ThinkingInfo,
    ToolCallInfo,
    ToolDefinition,
    UsageInfo,
)

__all__ = [
    # Core
    "CompletionInternalResult",
    "complete_internal",
    "get_or_create_session",
    "save_messages",
    "stream_completion",
    "update_provider_metadata",
    # Helpers
    "clear_adapter_cache",
    "extract_text_content",
    "get_adapter",
    "get_provider",
    "is_error_response",
    "normalize_content_for_storage",
    "parse_mention",
    "should_enable_thinking",
    "validate_json_response",
    # Schemas
    "CacheInfo",
    "CompletionRequest",
    "CompletionResponse",
    "ContainerInfo",
    "ContextUsageInfo",
    "EstimateRequest",
    "EstimateResponse",
    "MessageInput",
    "OutputUsageInfo",
    "ResponseFormat",
    "StreamingChunk",
    "ThinkingInfo",
    "ToolCallInfo",
    "ToolDefinition",
    "UsageInfo",
]
