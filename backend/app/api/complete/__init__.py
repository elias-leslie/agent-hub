"""Completion API package."""

from app.routing.registry import clear_cache as clear_adapter_cache
from app.routing.registry import get_provider_for_model as get_provider

from .async_endpoints import router as async_router
from .core import (
    CompletionInternalResult,
    complete_internal,
    stream_completion,
)
from .endpoints import router
from .event_helpers import save_events
from .helpers import (
    extract_text_content,
    is_error_response,
    normalize_content_for_storage,
    parse_mention,
    should_enable_thinking,
    validate_json_response,
)
from .schemas import (
    AsyncTaskResponse,
    AsyncTaskStatusResponse,
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
from .session_repo import get_or_create_session, update_provider_metadata

router.include_router(async_router)

__all__ = [
    "AsyncTaskResponse",
    "AsyncTaskStatusResponse",
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
    "async_router",
    "clear_adapter_cache",
    "complete_internal",
    "extract_text_content",
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
