"""Direct tool executors for agent tool execution.

Executes bash, read, write, and consult_agent tools directly with proper
environment inheritance. Commands run in the specified working directory
with full access to parent environment variables.

This module re-exports components from focused submodules while maintaining
backward compatibility with existing imports.
"""

from __future__ import annotations

# Core executor implementation
from app.services.tools.direct_executor_core import (
    BLOCKED_COMMANDS,
    DEFAULT_TIMEOUT,
    MAX_OUTPUT_SIZE,
    DirectToolExecutor,
    _get_command_redirect,
    _is_blocked_command,
)

# Registry-driven command redirect (centralized tool-registry.json)
from app.services.tools.registry import get_command_redirect

# Tool definitions
from app.services.tools.tool_definitions import STANDARD_TOOLS, get_standard_tools

# Tool handler and factory
from app.services.tools.tool_handler import DirectToolHandler, create_direct_handler

__all__ = [
    "BLOCKED_COMMANDS",
    "DEFAULT_TIMEOUT",
    "MAX_OUTPUT_SIZE",
    "STANDARD_TOOLS",
    "DirectToolExecutor",
    "DirectToolHandler",
    "_get_command_redirect",
    "_is_blocked_command",
    "create_direct_handler",
    "get_command_redirect",
    "get_standard_tools",
]
