"""Subagent data models."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal


@dataclass
class SubagentConfig:
    """Configuration for a subagent."""

    name: str
    """Human-readable name for the subagent."""

    provider: Literal["claude", "gemini"] = "claude"
    """Which provider to use."""

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

    timeout_seconds: float = 300.0
    """Maximum execution time before timeout."""


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
