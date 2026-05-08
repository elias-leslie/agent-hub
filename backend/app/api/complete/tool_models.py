"""Data models for tool execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentProgress:
    """Progress update during agent execution."""

    turn: int
    status: str
    message: str
    topic: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_results: list[dict[str, Any]] | None = None
    thinking: str | None = None


@dataclass
class ToolExecutionResult:
    """Result from tool execution handlers."""

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
    turns: int = 1
    tool_calls_count: int = 0
    status: str = "success"
    error: str | None = None
    container_id: str | None = None
    progress_log: list[AgentProgress] = field(default_factory=list)
    tool_result_summaries: list[str] = field(default_factory=list)
    error_summary: dict[str, Any] | None = None
    model_used: str | None = None
    fallback_used: bool = False
    requested_model: str | None = None
    requested_provider: str | None = None
    fallback_reason: str | None = None
