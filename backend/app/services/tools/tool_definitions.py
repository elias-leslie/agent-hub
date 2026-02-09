"""Standard tool definitions for agent tool execution.

Defines the schema and metadata for bash, read_file, write_file, and
consult_agent tools.
"""

from __future__ import annotations

from app.services.tools.base import Tool

# Default timeout for commands
DEFAULT_TIMEOUT = 120

# Standard tool definitions for agents
STANDARD_TOOLS = [
    Tool(
        name="bash",
        description="Execute a bash command in the working directory. Use for running tests, git operations, or system commands.",
        input_schema={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash command to execute",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 120)",
                    "default": DEFAULT_TIMEOUT,
                },
            },
            "required": ["command"],
        },
    ),
    Tool(
        name="read_file",
        description="Read contents of a file. Returns lines with line numbers.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path (absolute or relative to working directory)",
                },
                "offset": {
                    "type": "integer",
                    "description": "Line offset to start reading from (0-indexed)",
                    "default": 0,
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of lines to read",
                    "default": 2000,
                },
            },
            "required": ["path"],
        },
    ),
    Tool(
        name="write_file",
        description="Write content to a file. Creates parent directories if needed.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path (absolute or relative to working directory)",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file",
                },
            },
            "required": ["path", "content"],
        },
    ),
    Tool(
        name="consult_agent",
        description=(
            "Consult another agent for advice or help. Use when stuck on a problem, "
            "need expert review, or want a second opinion. The consulted agent will "
            "analyze your question and provide guidance but will not execute any tools. "
            "Available agents: 'supervisor' (coordination/strategy), 'reviewer' (code review)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "agent_slug": {
                    "type": "string",
                    "description": "The agent to consult (e.g., 'supervisor', 'reviewer')",
                },
                "question": {
                    "type": "string",
                    "description": "The question or problem to get help with",
                },
                "context": {
                    "type": "string",
                    "description": "Additional context about the current situation",
                    "default": "",
                },
            },
            "required": ["agent_slug", "question"],
        },
    ),
]


def get_standard_tools() -> list[Tool]:
    """Get standard tool definitions."""
    return STANDARD_TOOLS.copy()
