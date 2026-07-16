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


def _merge_system_contents(
    contents: list[str | list[dict[str, Any]]],
) -> str | list[dict[str, Any]]:
    """Merge ordered system content without losing structured text blocks."""
    if all(isinstance(content, str) for content in contents):
        return "\n\n".join(content for content in contents if isinstance(content, str) and content)

    blocks: list[dict[str, Any]] = []
    for content in contents:
        if isinstance(content, str):
            if content:
                blocks.append({"type": "text", "text": content})
        else:
            blocks.extend(dict(block) for block in content)
    return blocks


def append_system_context(
    messages: list[Message],
    system_content: str,
) -> list[Message]:
    """Return one leading system message with new context appended last.

    All existing system messages are retained in their original order even if
    a resumed conversation placed one after a user/assistant message. Keeping
    exactly one leading system message prevents provider adapters that accept a
    single system channel from silently dropping a later agent prompt.
    """
    system_contents = [message.content for message in messages if message.role == "system"]
    if system_content:
        system_contents.append(system_content)
    non_system = [message for message in messages if message.role != "system"]
    if not system_contents:
        return list(non_system)
    return [Message(role="system", content=_merge_system_contents(system_contents)), *non_system]


def prepend_system_context_dicts(
    messages: list[dict[str, Any]],
    system_content: str,
) -> list[dict[str, Any]]:
    """Return one leading system message with new context placed first.

    This is reserved for Agent Hub canonical operator context, whose
    guardrails and mandates must precede Agent Hub-owned agent/persona prompt
    content. Provider-native base instructions stay outside this message layer.
    """
    existing_system_contents = [
        message.get("content", "")
        for message in messages
        if message.get("role") == "system"
    ]
    system_contents = (
        [system_content, *existing_system_contents]
        if system_content
        else existing_system_contents
    )
    non_system = [dict(message) for message in messages if message.get("role") != "system"]
    if not system_contents:
        return non_system
    return [
        {"role": "system", "content": _merge_system_contents(system_contents)},
        *non_system,
    ]


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
