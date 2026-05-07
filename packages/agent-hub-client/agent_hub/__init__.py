"""Agent Hub Python Client SDK.

Provides Python clients for interacting with Agent Hub API.

Example usage:

    from agent_hub import AsyncAgentHubClient

    async with AsyncAgentHubClient(base_url="http://localhost:8003") as client:
        response = await client.complete(
            agent_slug="chat",
            messages=[{"role": "user", "content": "Hello!"}]
        )
        print(response.content)

    # Streaming
    async for chunk in client.stream_sse(
        agent_slug="chat",
        messages=[{"role": "user", "content": "Tell me a story"}]
    ):
        print(chunk.content, end="", flush=True)
"""

from agent_hub.client import AgentHubClient, AsyncAgentHubClient
from agent_hub.constants import (
    CHAT_AGENT,
    CODER_AGENT,
    DEFAULT_AGENT,
    DEFAULT_IMAGE_AGENT,
    IMAGE_AGENT,
    PROMPT_BUILDER_AGENT,
    REASONER_AGENT,
    REVIEWER_AGENT,
)
from agent_hub.exceptions import (
    AgentHubError,
    AuthenticationError,
    ClientDisabledError,
    RateLimitError,
    ServerError,
    ValidationError,
)
from agent_hub.models import (
    AgentProgress,
    CacheInfo,
    CompletionResponse,
    ContainerInfo,
    ContentBlock,
    ContextUsage,
    ImageContent,
    Message,
    MessageInput,
    RoutingConfig,
    SessionCreate,
    SessionResponse,
    StreamChunk,
    TextContent,
    ToolCall,
    ToolDefinition,
    ToolResultMessage,
    UsageInfo,
)
from agent_hub.session import Session, SessionContext

__version__ = "0.4.0"
__all__ = [
    # Clients
    "AgentHubClient",
    "AsyncAgentHubClient",
    # Session management
    "Session",
    "SessionContext",
    # Agent slug constants
    "CHAT_AGENT",
    "CODER_AGENT",
    "REASONER_AGENT",
    "REVIEWER_AGENT",
    "IMAGE_AGENT",
    "PROMPT_BUILDER_AGENT",
    "DEFAULT_AGENT",
    "DEFAULT_IMAGE_AGENT",
    # Models
    "AgentProgress",
    "CacheInfo",
    "CompletionResponse",
    "ContainerInfo",
    "ContentBlock",
    "ContextUsage",
    "ImageContent",
    "Message",
    "MessageInput",
    "RoutingConfig",
    "SessionCreate",
    "SessionResponse",
    "StreamChunk",
    "TextContent",
    "ToolCall",
    "ToolDefinition",
    "ToolResultMessage",
    "UsageInfo",
    # Exceptions
    "AgentHubError",
    "AuthenticationError",
    "ClientDisabledError",
    "RateLimitError",
    "ServerError",
    "ValidationError",
]
