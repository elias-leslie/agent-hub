"""Base types and interfaces for tool support."""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class ToolDecision(Enum):
    """Decision from pre-tool-use hook."""

    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"  # Requires user confirmation


# Supported caller types for programmatic tool calling
CallerType = Literal["direct", "code_execution_20250825"]


@dataclass
class Tool:
    """Definition of a tool that can be called by the model."""

    name: str
    description: str
    input_schema: dict[str, Any]
    # Programmatic tool calling: who can call this tool
    # ["direct"] = Claude calls directly (default)
    # ["code_execution_20250825"] = Only callable from code execution
    # ["direct", "code_execution_20250825"] = Both allowed
    allowed_callers: list[CallerType] = field(default_factory=lambda: ["direct"])


@dataclass
class ToolCaller:
    """Information about who called a tool (direct vs programmatic)."""

    type: CallerType
    tool_id: str | None = None  # Set when called from code_execution


@dataclass
class ToolCall:
    """A tool call from the model."""

    id: str
    name: str
    input: dict[str, Any]
    caller: ToolCaller = field(default_factory=lambda: ToolCaller(type="direct"))


@dataclass
class ToolResult:
    """Result from executing a tool."""

    tool_use_id: str
    content: str
    is_error: bool = False


@dataclass
class CodeExecutionTool:
    """
    The code_execution tool for programmatic tool calling.

    When included in tools, Claude can write code that calls other tools
    programmatically within a sandboxed execution environment.
    """

    type: str = "code_execution_20250825"
    name: str = "code_execution"

    def to_api_format(self) -> dict[str, Any]:
        """Convert to Claude API format."""
        return {
            "type": self.type,
            "name": self.name,
        }


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

    def to_api_format(
        self, provider: str, include_code_execution: bool = False
    ) -> list[dict[str, Any]]:
        """
        Convert tools to provider-specific API format.

        Args:
            provider: Target provider ("claude" or "gemini")
            include_code_execution: If True, prepend code_execution tool (Claude only)

        Returns:
            List of tool definitions in provider format
        """
        result: list[dict[str, Any]] = []

        # Add code_execution tool first if requested (Claude only)
        if include_code_execution and provider == "claude":
            result.append(CodeExecutionTool().to_api_format())

        if provider == "claude":
            for t in self.tools:
                tool_def: dict[str, Any] = {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                }
                # Only add allowed_callers if not default ["direct"]
                if t.allowed_callers != ["direct"]:
                    tool_def["allowed_callers"] = t.allowed_callers
                result.append(tool_def)
        elif provider == "gemini":
            # Gemini doesn't support programmatic tool calling
            # Include all tools regardless of allowed_callers
            for t in self.tools:
                result.append({
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                })
        else:
            raise ValueError(f"Unknown provider: {provider}")

        return result

    def is_caller_allowed(self, tool_name: str, caller_type: CallerType) -> bool:
        """
        Check if a caller type is allowed to invoke a tool.

        Args:
            tool_name: Name of the tool to check
            caller_type: The caller context (direct or code_execution_20250825)

        Returns:
            True if the caller is allowed to invoke this tool
        """
        tool = self.get(tool_name)
        if not tool:
            return False
        return caller_type in tool.allowed_callers


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
