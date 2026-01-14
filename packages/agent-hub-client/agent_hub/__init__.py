"""Agent Hub Python Client SDK.

Provides sync and async clients for interacting with Agent Hub API.

Example usage:

    # Sync client
    from agent_hub import AgentHubClient

    client = AgentHubClient(base_url="http://localhost:8003")
    response = client.complete(
        model="claude-sonnet-4-5",
        messages=[{"role": "user", "content": "Hello!"}]
    )
    print(response.content)

    # Async client
    from agent_hub import AsyncAgentHubClient

    async with AsyncAgentHubClient(base_url="http://localhost:8003") as client:
        response = await client.complete(
            model="claude-sonnet-4-5",
            messages=[{"role": "user", "content": "Hello!"}]
        )
        print(response.content)

    # Streaming
    async for chunk in client.stream(
        model="claude-sonnet-4-5",
        messages=[{"role": "user", "content": "Tell me a story"}]
    ):
        print(chunk.content, end="", flush=True)
"""

from agent_hub.client import AgentHubClient, AsyncAgentHubClient
from agent_hub.exceptions import (
    AgentHubError,
    AuthenticationError,
    RateLimitError,
    ServerError,
    ValidationError,
)
from agent_hub.models import (
    AgentProgress,
    AgentRunRequest,
    AgentRunResponse,
    CacheInfo,
    CompletionRequest,
    CompletionResponse,
    ContainerInfo,
    ContentBlock,
    ContextUsage,
    ImageContent,
    Message,
    MessageInput,
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

__version__ = "0.1.0"
__all__ = [
    # Clients
    "AgentHubClient",
    "AsyncAgentHubClient",
    # Session management
    "Session",
    "SessionContext",
    # Models
    "AgentProgress",
    "AgentRunRequest",
    "AgentRunResponse",
    "CacheInfo",
    "CompletionRequest",
    "CompletionResponse",
    "ContainerInfo",
    "ContentBlock",
    "ContextUsage",
    "ImageContent",
    "Message",
    "MessageInput",
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
    "RateLimitError",
    "ServerError",
    "ValidationError",
]
