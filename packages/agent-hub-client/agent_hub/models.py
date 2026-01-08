"""Pydantic models for Agent Hub client."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class MessageInput(BaseModel):
    """Input message for completion request."""

    role: Literal["user", "assistant", "system"] = Field(
        ..., description="Message role"
    )
    content: str = Field(..., description="Message content")


class Message(BaseModel):
    """Message with full metadata (from session history)."""

    id: int
    role: str
    content: str
    tokens: int | None = None
    created_at: datetime


class CacheInfo(BaseModel):
    """Prompt cache usage information."""

    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_hit_rate: float = 0.0


class UsageInfo(BaseModel):
    """Token usage information."""

    input_tokens: int
    output_tokens: int
    total_tokens: int
    cache: CacheInfo | None = None


class ContextUsage(BaseModel):
    """Context window usage information."""

    used_tokens: int = Field(..., description="Tokens currently in context")
    limit_tokens: int = Field(..., description="Model's context window limit")
    percent_used: float = Field(..., description="Percentage of context used")
    remaining_tokens: int = Field(..., description="Tokens available")
    warning: str | None = Field(default=None, description="Warning if approaching limit")


class ToolDefinition(BaseModel):
    """Tool definition for model to call."""

    name: str = Field(..., description="Tool name")
    description: str = Field(..., description="Tool description")
    input_schema: dict[str, Any] = Field(..., description="JSON Schema for tool parameters")
    allowed_callers: list[str] = Field(
        default_factory=lambda: ["direct"],
        description="Who can call this tool: direct, code_execution_20250825",
    )


class ToolCall(BaseModel):
    """A tool call requested by the model."""

    id: str = Field(..., description="Unique ID for this tool call")
    name: str = Field(..., description="Tool name")
    input: dict[str, Any] = Field(..., description="Tool input parameters")
    caller_type: str = Field(default="direct", description="Who initiated: direct or code_execution")
    caller_tool_id: str | None = Field(default=None, description="Tool ID if called from code execution")


class ToolResultMessage(BaseModel):
    """Tool result message to send back to the model."""

    role: Literal["user"] = "user"
    content: list[dict[str, Any]] = Field(..., description="Tool result content blocks")

    @classmethod
    def from_result(
        cls,
        tool_use_id: str,
        result: str,
        is_error: bool = False,
    ) -> "ToolResultMessage":
        """Create a tool result message from execution result.

        Args:
            tool_use_id: The tool call ID this result corresponds to.
            result: The tool execution result (or error message).
            is_error: Whether this is an error result.

        Returns:
            ToolResultMessage ready to send to the API.
        """
        return cls(
            content=[
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": result,
                    **({"is_error": True} if is_error else {}),
                }
            ]
        )


class ContainerInfo(BaseModel):
    """Container state for programmatic tool calling."""

    id: str = Field(..., description="Container ID for continuity")
    expires_at: str = Field(..., description="Container expiration timestamp")


class CompletionRequest(BaseModel):
    """Request body for completion endpoint."""

    model: str = Field(..., description="Model identifier")
    messages: list[MessageInput] = Field(..., description="Conversation messages")
    max_tokens: int = Field(default=4096, ge=1, le=100000)
    temperature: float = Field(default=1.0, ge=0.0, le=2.0)
    session_id: str | None = Field(default=None)
    project_id: str = Field(default="default")
    enable_caching: bool = Field(default=True)
    cache_ttl: str = Field(default="ephemeral")
    persist_session: bool = Field(default=True)
    # Tool calling support
    tools: list[ToolDefinition] | None = Field(default=None, description="Tool definitions")
    enable_programmatic_tools: bool = Field(default=False, description="Enable code execution")
    container_id: str | None = Field(default=None, description="Container ID for continuity")


class CompletionResponse(BaseModel):
    """Response from completion endpoint."""

    content: str = Field(..., description="Generated content")
    model: str = Field(..., description="Model used")
    provider: str = Field(..., description="Provider that served request")
    usage: UsageInfo = Field(..., description="Token usage")
    context_usage: ContextUsage | None = Field(default=None)
    session_id: str = Field(..., description="Session ID")
    finish_reason: str | None = Field(default=None)
    from_cache: bool = Field(default=False)
    # Tool calling (when model requests tool execution)
    tool_calls: list[ToolCall] | None = Field(default=None, description="Tool calls to execute")
    container: ContainerInfo | None = Field(default=None, description="Container state")


class StreamChunk(BaseModel):
    """Chunk from streaming response."""

    type: Literal["content", "done", "cancelled", "error"] = Field(
        ..., description="Event type"
    )
    content: str = Field(default="", description="Content for 'content' events")
    input_tokens: int | None = Field(default=None)
    output_tokens: int | None = Field(default=None)
    finish_reason: str | None = Field(default=None)
    error: str | None = Field(default=None)


class SessionCreate(BaseModel):
    """Request to create a new session."""

    project_id: str = Field(..., description="Project identifier")
    provider: str = Field(..., description="Provider: claude or gemini")
    model: str = Field(..., description="Model identifier")


class SessionResponse(BaseModel):
    """Response from session operations."""

    id: str
    project_id: str
    provider: str
    model: str
    status: str
    created_at: datetime
    updated_at: datetime
    messages: list[Message] = Field(default_factory=list)
    context_usage: ContextUsage | None = Field(default=None)


class SessionListItem(BaseModel):
    """Session item in list response."""

    id: str
    project_id: str
    provider: str
    model: str
    status: str
    message_count: int
    created_at: datetime
    updated_at: datetime


class SessionListResponse(BaseModel):
    """Response from listing sessions."""

    sessions: list[SessionListItem]
    total: int
    page: int
    page_size: int
