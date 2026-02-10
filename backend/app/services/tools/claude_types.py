"""Data types for Claude tool calling."""

from dataclasses import dataclass, field
from typing import Any

from anthropic.types import ContentBlock

from app.services.tools.base import ToolCall


@dataclass
class ServerToolUse:
    """Server-side tool use block (e.g., code_execution)."""

    id: str
    name: str
    input: dict[str, Any]


@dataclass
class CodeExecutionResult:
    """Result from code execution tool."""

    stdout: str
    stderr: str
    return_code: int
    content: list[Any] = field(default_factory=list)  # Files created


@dataclass
class ContainerInfo:
    """Container information from API response."""

    id: str
    expires_at: str


@dataclass
class ClaudeToolResponse:
    """Response from Claude that may contain tool calls."""

    text_content: str
    tool_calls: list[ToolCall]
    stop_reason: str | None
    raw_blocks: list[ContentBlock]
    # Programmatic tool calling fields
    server_tool_uses: list[ServerToolUse] = field(default_factory=list)
    code_execution_results: list[CodeExecutionResult] = field(default_factory=list)
    container: ContainerInfo | None = None
