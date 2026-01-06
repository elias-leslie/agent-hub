"""Base types and interfaces for tool support."""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ToolDecision(Enum):
    """Decision from pre-tool-use hook."""

    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"  # Requires user confirmation


@dataclass
class Tool:
    """Definition of a tool that can be called by the model."""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class ToolCall:
    """A tool call from the model."""

    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ToolResult:
    """Result from executing a tool."""

    tool_use_id: str
    content: str
    is_error: bool = False


@dataclass
class ToolRegistry:
    """Registry of available tools."""

    tools: list[Tool] = field(default_factory=list)

    def add(self, tool: Tool) -> None:
        """Add a tool to the registry."""
        self.tools.append(tool)

    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        for tool in self.tools:
            if tool.name == name:
                return tool
        return None

    def to_api_format(self, provider: str) -> list[dict[str, Any]]:
        """Convert tools to provider-specific API format."""
        if provider == "claude":
            return [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                }
                for t in self.tools
            ]
        elif provider == "gemini":
            # Gemini uses function_declarations format
            return [
                {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                }
                for t in self.tools
            ]
        else:
            raise ValueError(f"Unknown provider: {provider}")


# Type for pre-tool-use hook callback
PreToolUseHook = Callable[[ToolCall], Awaitable[ToolDecision]]


class ToolHandler(ABC):
    """Abstract handler for tool execution with hooks."""

    def __init__(self, pre_hook: PreToolUseHook | None = None):
        """
        Initialize handler.

        Args:
            pre_hook: Optional async callback called before each tool execution.
                      Returns ToolDecision indicating whether to proceed.
        """
        self._pre_hook = pre_hook

    async def check_permission(self, tool_call: ToolCall) -> ToolDecision:
        """Check if tool call is permitted."""
        if self._pre_hook:
            return await self._pre_hook(tool_call)
        return ToolDecision.ALLOW

    @abstractmethod
    async def execute(self, tool_call: ToolCall) -> ToolResult:
        """Execute a tool call and return result."""
        ...
