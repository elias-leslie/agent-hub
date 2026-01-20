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
from agent_hub.constants import (
    CLAUDE_HAIKU,
    CLAUDE_OPUS,
    CLAUDE_SONNET,
    DEFAULT_CLAUDE_MODEL,
    DEFAULT_GEMINI_MODEL,
    FAST_CLAUDE_MODEL,
    FAST_GEMINI_MODEL,
    GEMINI_FLASH,
    GEMINI_PRO,
    REASONING_CLAUDE_MODEL,
    REASONING_GEMINI_MODEL,
)
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

__version__ = "0.1.0"
__all__ = [
    # Clients
    "AgentHubClient",
    "AsyncAgentHubClient",
    # Session management
    "Session",
    "SessionContext",
    # Model constants
    "CLAUDE_SONNET",
    "CLAUDE_OPUS",
    "CLAUDE_HAIKU",
    "GEMINI_FLASH",
    "GEMINI_PRO",
    "DEFAULT_CLAUDE_MODEL",
    "DEFAULT_GEMINI_MODEL",
    "REASONING_CLAUDE_MODEL",
    "REASONING_GEMINI_MODEL",
    "FAST_CLAUDE_MODEL",
    "FAST_GEMINI_MODEL",
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
    "RateLimitError",
    "ServerError",
    "ValidationError",
]
