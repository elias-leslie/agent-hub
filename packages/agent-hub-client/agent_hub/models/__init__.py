"""Models subpackage for Agent Hub client."""

from agent_hub.models.agent import AgentProgress, AgentRunRequest, AgentRunResponse
from agent_hub.models.content import (
    ContentBlock,
    ImageContent,
    Message,
    MessageInput,
    TextContent,
)
from agent_hub.models.core import (
    CompletionRequest,
    CompletionResponse,
    ContainerInfo,
    RoutingConfig,
    StreamChunk,
)
from agent_hub.models.image import ImageGenerationResponse
from agent_hub.models.session import (
    SessionCreate,
    SessionListItem,
    SessionListResponse,
    SessionResponse,
)
from agent_hub.models.tools import ToolCall, ToolDefinition, ToolResultMessage
from agent_hub.models.usage import CacheInfo, ContextUsage, UsageInfo

__all__ = [
    # Content models
    "TextContent",
    "ImageContent",
    "ContentBlock",
    "MessageInput",
    "Message",
    # Usage models
    "CacheInfo",
    "UsageInfo",
    "ContextUsage",
    # Tool models
    "ToolDefinition",
    "ToolCall",
    "ToolResultMessage",
    # Core models
    "ContainerInfo",
    "RoutingConfig",
    "CompletionRequest",
    "CompletionResponse",
    "StreamChunk",
    # Session models
    "SessionCreate",
    "SessionResponse",
    "SessionListItem",
    "SessionListResponse",
    # Image models
    "ImageGenerationResponse",
    # Agent models
    "AgentRunRequest",
    "AgentProgress",
    "AgentRunResponse",
]
