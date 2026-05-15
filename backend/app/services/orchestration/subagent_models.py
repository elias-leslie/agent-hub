"""Subagent data models."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

DEFAULT_MAX_SPAWN_DEPTH = 3
DEFAULT_MAX_CONTEXT_MESSAGES = 6
DEFAULT_MAX_CONTEXT_CHARS = 4000


@dataclass
class SubagentConfig:
    """Configuration for a subagent."""

    name: str
    """Human-readable name for the subagent."""

    provider: str = "gemini"
    """Which provider to use (validated by registry at adapter resolution)."""

    model: str | None = None
    """Model override. If None, uses provider default."""

    system_prompt: str | None = None
    """Custom system prompt. If None, uses default."""

    temperature: float = 1.0
    """Sampling temperature."""

    thinking_level: str | None = None
    """Thinking depth: minimal/low/medium/high/ultrathink."""

    tools: list[dict[str, Any]] | None = None
    """Tool definitions available to this subagent."""

    timeout_seconds: float | None = None
    """Deprecated metadata only. Active subagent execution waits for completion."""

    max_spawn_depth: int = DEFAULT_MAX_SPAWN_DEPTH
    """Maximum nesting depth for subagent spawning (0 = no children)."""

    current_depth: int = 0
    """Current depth in the spawn hierarchy (0 = top-level)."""

    project_id: str | None = None
    """Project ID for cost tracking. When set, token usage is logged to CostLog."""

    context_mode: Literal["focused", "full", "none"] = "focused"
    """How parent context is forwarded to the child."""

    max_context_messages: int = DEFAULT_MAX_CONTEXT_MESSAGES
    """Maximum parent-context messages to keep when context_mode='focused'."""

    max_context_chars: int = DEFAULT_MAX_CONTEXT_CHARS
    """Maximum combined context characters to forward when context_mode='focused'."""


@dataclass
class SubagentResult:
    """Result from a subagent execution."""

    subagent_id: str
    """Unique ID for this subagent instance."""

    name: str
    """Name of the subagent."""

    content: str
    """Response content from the subagent."""

    status: Literal["completed", "error", "timeout", "cancelled"]
    """Execution status."""

    provider: str
    """Provider that handled the request."""

    model: str
    """Model used."""

    input_tokens: int
    """Input tokens consumed."""

    output_tokens: int
    """Output tokens generated."""

    thinking_content: str | None = None
    """Extended thinking content (if enabled)."""

    thinking_tokens: int | None = None
    """Tokens used for thinking."""

    error: str | None = None
    """Error message if status is 'error'."""

    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    """When execution started."""

    completed_at: datetime | None = None
    """When execution completed."""

    parent_id: str | None = None
    """ID of parent subagent (for nested hierarchies)."""

    trace_id: str | None = None
    """OpenTelemetry trace ID for correlation."""
