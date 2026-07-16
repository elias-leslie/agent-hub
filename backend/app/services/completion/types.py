"""Types for the completion service."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class CompletionSource(StrEnum):
    """Source type for completion requests."""

    CHAT = "chat"  # REST /api/complete
    VOICE = "voice"  # WebSocket /api/voice/ws
    STREAM = "stream"  # WebSocket /api/stream


@dataclass
class CompletionOptions:
    """Options for completion request."""

    model: str
    messages: list[dict[str, Any]]
    project_id: str
    max_tokens: int | None = None
    temperature: float = 1.0
    session_id: str | None = None
    external_id: str | None = None
    source: CompletionSource = CompletionSource.CHAT

    # Memory options
    use_memory: bool = False
    memory_group_id: str | None = None
    memory_variant_override: str | None = None
    store_as_episode: bool = False  # Store conversation in memory after completion

    # Caching
    enable_caching: bool = True
    cache_ttl: str = "ephemeral"

    # Structured output
    response_format: dict[str, Any] | None = None

    # Extended thinking
    thinking_level: str | None = None  # minimal/low/medium/high/ultrathink
    auto_thinking: bool = False

    # Tools
    tools: list[dict[str, Any]] | None = None
    enable_programmatic_tools: bool = False
    container_id: str | None = None

    # Memory-triggered references
    task_type: str | None = None
    phase: str | None = None

    # Per-agent memory overrides (from Agent.memory_config)
    memory_config: dict[str, Any] | None = None

    # Branch context for continuity scoping
    current_branch: str | None = None

    # Canonical context applicability metadata.
    agent_slug: str | None = None
    consumer_surface: str | None = None


@dataclass
class CompletionServiceResult:
    """Result from completion service."""

    content: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    session_id: str
    finish_reason: str | None = None
    thinking_content: str | None = None
    thinking_tokens: int | None = None
    tool_calls: list[Any] | None = None
    container: Any | None = None
    cache_metrics: Any | None = None
    memory_facts_injected: int = 0
    episode_uuid: str | None = None  # UUID of stored memory episode
