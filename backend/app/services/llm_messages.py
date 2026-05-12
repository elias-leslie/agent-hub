"""Core types for provider adapters."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal


class ThinkingLevel(StrEnum):
    OFF = "off"
    NONE = "none"
    MINIMAL = "minimal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    ULTRATHINK = "ultrathink"


@dataclass
class StreamEvent:
    """Event from streaming completion."""

    type: Literal["content", "done", "error", "thinking", "tool_use", "tool_result", "turn_start", "turn_end"]
    content: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None
    error: str | None = None
    # Extended thinking support
    thinking_tokens: int | None = None  # Tokens used for thinking
    # Tool use support (for streaming tool calls back to frontend)
    tool_id: str | None = None
    tool_name: str | None = None
    tool_input: dict[str, Any] | None = None
    is_error: bool = False
    duration_ms: int | None = None
    # CloudCode PA: thoughtSignature required on functionCall parts when thinking is enabled
    thought_signature: str | None = None
    # Turn lifecycle (emitted by tool execution loops)
    turn: int | None = None


@dataclass
class Message:
    """A message in a conversation.

    Content can be:
    - str: Simple text content
    - list[dict]: Content blocks for vision (text + image)

    Image block format:
    {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": "<base64-encoded-data>"
        }
    }
    """

    role: Literal["user", "assistant", "system"]
    content: str | list[dict[str, Any]]
    # Provenance — tracks which provider/model produced this message
    provider: str | None = None
    model: str | None = None

    def has_images(self) -> bool:
        """Check if this message contains image content."""
        if isinstance(self.content, str):
            return False
        return any(
            isinstance(block, dict) and block.get("type") == "image" for block in self.content
        )


@dataclass
class CacheMetrics:
    """Cache usage metrics for prompt caching."""

    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    @property
    def cache_hit_rate(self) -> float:
        """Calculate cache hit rate (0.0-1.0)."""
        total = self.cache_creation_input_tokens + self.cache_read_input_tokens
        if total == 0:
            return 0.0
        return self.cache_read_input_tokens / total


@dataclass
class ToolCallResult:
    """A tool call in a completion response (for programmatic tool calling)."""

    id: str
    name: str
    input: dict[str, Any]
    caller_type: str = "direct"  # "direct" or "code_execution_20250825"
    caller_tool_id: str | None = None  # Set when called from code_execution
    original_id: str | None = None  # Original ID before normalization (for debugging)


@dataclass
class ContainerState:
    """Container state for programmatic tool calling."""

    id: str
    expires_at: str  # ISO timestamp


@dataclass
class CompletionResult:
    """Result from a completion request."""

    content: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    finish_reason: str | None = None
    raw_response: Any = None
    cache_metrics: CacheMetrics | None = None
    # Programmatic tool calling fields
    tool_calls: list[ToolCallResult] | None = None
    container: ContainerState | None = None
    # Extended thinking fields
    thinking_content: str | None = None
    thinking_tokens: int | None = None
    # Why the primary model was abandoned, when fallback routing succeeded.
    fallback_reason: str | None = None
