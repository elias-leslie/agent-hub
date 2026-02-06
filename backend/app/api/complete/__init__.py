"""Completion API package."""

from app.services.agent_routing import get_provider_for_model as get_provider

from .core import (
    CompletionInternalResult,
    complete_internal,
    get_or_create_session,
    save_events,
    stream_completion,
    update_provider_metadata,
)
from .endpoints import router
from .helpers import (
    clear_adapter_cache,
    extract_text_content,
    get_adapter,
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
    "CacheInfo",
    "CompletionInternalResult",
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
    "clear_adapter_cache",
    "complete_internal",
    "extract_text_content",
    "get_adapter",
    "get_or_create_session",
    "get_provider",
    "is_error_response",
    "normalize_content_for_storage",
    "parse_mention",
    "router",
    "save_events",
    "should_enable_thinking",
    "stream_completion",
    "update_provider_metadata",
    "validate_json_response",
]
