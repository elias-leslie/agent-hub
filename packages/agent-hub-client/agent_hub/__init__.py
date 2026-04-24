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
    CLAUDE_HAIKU,
    CLAUDE_OPUS,
    CLAUDE_SONNET,
    CODEX_GPT_5_5,
    DEFAULT_CLAUDE_MODEL,
    DEFAULT_GEMINI_MODEL,
    DEFAULT_IMAGE_MODEL,
    FAST_CLAUDE_MODEL,
    FAST_GEMINI_MODEL,
    GEMINI_3_1_FLASH_LITE,
    GEMINI_3_1_PRO,
    GEMINI_FLASH,
    GEMINI_IMAGE,
    GEMINI_PRO,
    REASONING_CLAUDE_MODEL,
    REASONING_GEMINI_MODEL,
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

__version__ = "0.3.0"
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
    "GEMINI_3_1_PRO",
    "GEMINI_3_1_FLASH_LITE",
    "GEMINI_IMAGE",
    "CODEX_GPT_5_5",
    "DEFAULT_CLAUDE_MODEL",
    "DEFAULT_GEMINI_MODEL",
    "DEFAULT_IMAGE_MODEL",
    "REASONING_CLAUDE_MODEL",
    "REASONING_GEMINI_MODEL",
    "FAST_CLAUDE_MODEL",
    "FAST_GEMINI_MODEL",
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
