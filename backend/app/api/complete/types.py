"""Type definitions for completion API."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .tool_handlers import AgentProgress


@dataclass
class CompletionInternalResult:
    """Result from complete_internal() for completion operations."""

    content: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    finish_reason: str | None
    session_id: str
    memory_uuids: list[str]
    cited_uuids: list[str]
    from_cache: bool = False
    cache_metrics: Any | None = None
    thinking_content: str | None = None
    thinking_tokens: int | None = None
    tool_calls: list[Any] | None = None
    container: Any | None = None
    # Multi-turn execution fields
    turns: int = 1
    tool_calls_count: int = 0
    status: str = "success"
    error: str | None = None
    container_id: str | None = None
    progress_log: list[AgentProgress] = field(default_factory=list)
    error_summary: dict[str, Any] | None = None
    # Fallback tracking
    model_used: str | None = None
    fallback_used: bool = False
    requested_model: str | None = None
    requested_provider: str | None = None
    fallback_reason: str | None = None
