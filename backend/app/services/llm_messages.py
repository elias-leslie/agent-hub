"""Legacy wire helpers retained outside the deleted text adapters."""

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
