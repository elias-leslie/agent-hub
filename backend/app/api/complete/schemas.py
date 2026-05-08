"""Request/Response schemas for completion API.

This module re-exports all schemas from focused submodules for backward compatibility.
"""

from __future__ import annotations

from .request_schemas import (
    AdhocWorkSpec,
    CompletionRequest,
    EstimateRequest,
    MessageInput,
    ResponseFormat,
    RoutingJudgment,
    RoutingPreferences,
    SourceMetadata,
    ToolDefinition,
    WorkContext,
)
from .response_schemas import (
    AsyncTaskResponse,
    AsyncTaskStatusResponse,
    CompletionResponse,
    EstimateResponse,
    StreamingChunk,
)
from .usage_schemas import (
    CacheInfo,
    ContainerInfo,
    ContextUsageInfo,
    OutputUsageInfo,
    ThinkingInfo,
    ToolCallInfo,
    UsageInfo,
)

__all__ = [
    "AdhocWorkSpec",
    "AsyncTaskResponse",
    "AsyncTaskStatusResponse",
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
    "RoutingJudgment",
    "RoutingPreferences",
    "SourceMetadata",
    "StreamingChunk",
    "ThinkingInfo",
    "ToolCallInfo",
    "ToolDefinition",
    "UsageInfo",
    "WorkContext",
]
