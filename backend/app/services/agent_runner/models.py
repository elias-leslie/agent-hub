"""Data models for agent runner."""

from dataclasses import dataclass, field
from typing import Any, Literal

from app.services.tools.base import Tool, ToolHandler

# Maximum turns for agentic loop (safety limit)
MAX_AGENT_TURNS = 20


@dataclass
class AgentProgress:
    """Progress update from agent execution."""

    turn: int
    status: str  # "running", "tool_use", "thinking", "complete", "error"
    message: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    thinking: str | None = None


@dataclass
class AgentResult:
    """Result from agent execution."""

    agent_id: str
    status: str  # "success", "error", "max_turns"
    content: str
    provider: str
    model: str
    turns: int
    input_tokens: int
    output_tokens: int
    thinking_tokens: int = 0
    tool_calls_count: int = 0
    error: str | None = None
    progress_log: list[AgentProgress] = field(default_factory=list)
    container_id: str | None = None  # For Claude code execution
    session_id: str | None = None  # Real DB session for tracking
    memory_uuids: list[str] = field(default_factory=list)  # Loaded memory UUIDs
    cited_uuids: list[str] = field(default_factory=list)  # Referenced memory UUIDs


@dataclass
class AgentConfig:
    """Configuration for agent execution."""

    provider: Literal["claude", "gemini"] = "claude"
    model: str | None = None
    system_prompt: str | None = None
    temperature: float = 1.0
    max_turns: int = MAX_AGENT_TURNS
    # Extended thinking
    thinking_level: str | None = None  # minimal/low/medium/high/ultrathink
    enable_code_execution: bool = True  # Use programmatic tools
    container_id: str | None = None  # Reuse existing container
    working_dir: str | None = None  # Working directory for agent execution
    # Gemini-specific
    tools: list[Tool] | None = None
    tool_handler: ToolHandler | None = None
    # Session tracking
    project_id: str = "default"  # Required for session creation
    use_memory: bool = True  # Inject memory on first turn
    memory_group_id: str | None = None  # Memory group for isolation
    # Agent routing
    agent_slug: str | None = None  # Agent slug for metrics attribution
