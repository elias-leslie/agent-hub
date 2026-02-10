"""Claude tool calling support using Anthropic SDK.

This module provides backward-compatible exports while delegating
implementation to focused submodules.
"""

# Re-export formatters
from app.services.tools.claude_formatters import (
    format_continuation_message,
    format_tool_result,
    format_tools_for_api,
)

# Re-export handler
from app.services.tools.claude_handler import ClaudeToolHandler

# Re-export parser
from app.services.tools.claude_parser import parse_tool_calls

# Re-export types
from app.services.tools.claude_types import (
    ClaudeToolResponse,
    CodeExecutionResult,
    ContainerInfo,
    ServerToolUse,
)

__all__ = [
    "ClaudeToolHandler",
    "ClaudeToolResponse",
    "CodeExecutionResult",
    "ContainerInfo",
    "ServerToolUse",
    "format_continuation_message",
    "format_tool_result",
    "format_tools_for_api",
    "parse_tool_calls",
]
